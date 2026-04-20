import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.account import Account, AccountStatus, AccountType
from app.models.proxy import Proxy
from app.schemas.account import AccountCreate, AccountUpdate
from app.config import settings

logger = logging.getLogger(__name__)


class AccountService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_account(self, data: AccountCreate, proxy_provider=None) -> Account:
        """Create a new account."""
        account = Account(
            email=str(data.email),
            display_name=data.display_name,
            type=data.type,
            proxy_id=data.proxy_id,
            status=AccountStatus.NEW
        )

        # If password provided, store plaintext for dashboard display
        if hasattr(data, 'password') and data.password:
            account.password_plain = data.password

        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(account)

        # Auto-provision proxy if no proxy was provided and provider is available
        if not account.proxy_id and proxy_provider and settings.PROXY_AUTO_PROVISION:
            try:
                proxy = await proxy_provider.provision_proxy()
                account.proxy_id = proxy.id
                await self.db.commit()
                await self.db.refresh(account)
                logger.info(f"Auto-provisioned proxy {proxy.host}:{proxy.port} for {account.email}")
            except Exception as e:
                logger.warning(f"Failed to auto-provision proxy for {account.email}: {e}")

        logger.info(f"Created account {account.email}")
        return account

    async def import_accounts_from_csv(self, csv_content: str, proxy_provider=None) -> list[Account]:
        """Import accounts from CSV. Expected columns: email,password,type"""
        import csv
        from io import StringIO

        accounts = []
        f = StringIO(csv_content)
        reader = csv.DictReader(f)

        for row in reader:
            account = Account(
                email=row['email'],
                display_name=row.get('display_name'),
                type=row.get('type', 'free'),
                status=AccountStatus.NEW
            )
            if 'password' in row and row['password']:
                account.password_plain = row['password']
            self.db.add(account)
            accounts.append(account)

        await self.db.commit()
        for acc in accounts:
            await self.db.refresh(acc)

        # Auto-provision proxies for imported accounts
        if proxy_provider and settings.PROXY_AUTO_PROVISION:
            for acc in accounts:
                if not acc.proxy_id:
                    try:
                        proxy = await proxy_provider.provision_proxy()
                        acc.proxy_id = proxy.id
                        logger.info(f"Auto-provisioned proxy for {acc.email}: {proxy.host}:{proxy.port}")
                    except Exception as e:
                        logger.warning(f"Failed to auto-provision proxy for {acc.email}: {e}")
            await self.db.commit()

        logger.info(f"Imported {len(accounts)} accounts from CSV")
        return accounts

    async def get_account(self, account_id: uuid.UUID) -> Optional[Account]:
        """Get account by ID."""
        result = await self.db.execute(
            select(Account).where(Account.id == account_id)
        )
        return result.scalar_one_or_none()

    async def update_account(self, account_id: uuid.UUID, data: AccountUpdate, proxy_provider=None) -> Account:
        """Update account fields."""
        result = await self.db.execute(
            select(Account).where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise ValueError(f"Account {account_id} not found")

        update_data = data.model_dump(exclude_unset=True)
        proxy_id_to_burn = None
        if update_data.get('status') == AccountStatus.BANNED:
            proxy_id_to_burn = account.proxy_id

        if 'password' in update_data:
            account.password_plain = update_data.pop('password')
        for field, value in update_data.items():
            setattr(account, field, value)

        account.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(account)

        if proxy_id_to_burn and proxy_provider:
            try:
                await proxy_provider.release_proxy(proxy_id_to_burn)
                logger.info(f"Burned proxy {proxy_id_to_burn} for banned account {account.email}")
            except Exception as e:
                logger.warning(f"Failed to burn proxy {proxy_id_to_burn} for banned account {account.email}: {e}")

        return account

    async def link_proxy(self, account_id: uuid.UUID, proxy_id: uuid.UUID) -> Account:
        """Link a proxy to an account (1:1)."""
        result = await self.db.execute(
            select(Account).where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise ValueError(f"Account {account_id} not found")

        # Check proxy exists
        proxy_result = await self.db.execute(
            select(Proxy).where(Proxy.id == proxy_id)
        )
        proxy = proxy_result.scalar_one_or_none()
        if not proxy:
            raise ValueError(f"Proxy {proxy_id} not found")

        account.proxy_id = proxy_id
        await self.db.commit()
        await self.db.refresh(account)
        logger.info(f"Linked proxy {proxy_id} to account {account.email}")
        return account

    async def set_cooldown(self, account_id: uuid.UUID, hours: Optional[int] = None) -> Account:
        """Set account cooldown."""
        from app.models.setting import Setting

        result = await self.db.execute(
            select(Account).where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise ValueError(f"Account {account_id} not found")

        if hours is None:
            # Get from settings
            setting_result = await self.db.execute(
                select(Setting).where(Setting.key == "cooldown_hours")
            )
            setting = setting_result.scalar_one_or_none()
            hours = int(setting.value) if setting else 6

        account.status = AccountStatus.COOLDOWN
        account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=hours)
        await self.db.commit()
        await self.db.refresh(account)
        logger.info(f"Set cooldown for account {account.email} until {account.cooldown_until}")
        return account

    async def force_active(self, account_id: uuid.UUID) -> Account:
        """Force account status to active."""
        result = await self.db.execute(
            select(Account).where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise ValueError(f"Account {account_id} not found")

        account.status = AccountStatus.ACTIVE
        account.cooldown_until = None
        await self.db.commit()
        await self.db.refresh(account)
        logger.info(f"Forced account {account.email} to active")
        return account

    async def delete_account(self, account_id: uuid.UUID, proxy_provider=None) -> bool:
        """Delete an account."""
        result = await self.db.execute(
            select(Account).where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise ValueError(f"Account {account_id} not found")

        # Burn proxy if provider is configured
        proxy_id_to_burn = account.proxy_id

        await self.db.delete(account)
        await self.db.commit()

        if proxy_id_to_burn and proxy_provider:
            try:
                await proxy_provider.release_proxy(proxy_id_to_burn)
                logger.info(f"Burned proxy {proxy_id_to_burn} for deleted account {account.email}")
            except Exception as e:
                logger.warning(f"Failed to burn proxy {proxy_id_to_burn}: {e}")

        logger.info(f"Deleted account {account.email}")
        return True
