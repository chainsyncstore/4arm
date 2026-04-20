import asyncio
import logging
import os
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)


class ADBService:
    """Android Debug Bridge service for controlling Redroid instances."""

    def __init__(self):
        self.mock_mode = settings.MOCK_ADB

    async def _run_adb(self, *args: str) -> tuple[int, str, str]:
        """Run an ADB command via asyncio subprocess and return (returncode, stdout, stderr)."""
        cmd = ["adb", *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            return (
                proc.returncode or 0,
                stdout_bytes.decode("utf-8", errors="replace"),
                stderr_bytes.decode("utf-8", errors="replace"),
            )
        except FileNotFoundError:
            logger.error("adb binary not found on PATH")
            return (1, "", "adb not found")
        except Exception as e:
            logger.error(f"ADB subprocess error: {e}")
            return (1, "", str(e))

    async def connect(self, host: str, port: int) -> bool:
        """Connect ADB to a Redroid instance."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: connect {host}:{port}")
            return True
        rc, stdout, stderr = await self._run_adb("connect", f"{host}:{port}")
        success = rc == 0 and "connected" in stdout.lower()
        if not success:
            logger.warning(f"ADB connect failed: {stdout} {stderr}")
        return success

    async def install_apk(self, device_id: str, apk_path: str) -> bool:
        """Install APK on device."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: install_apk {device_id} {apk_path}")
            return True
        rc, stdout, stderr = await self._run_adb("-s", device_id, "install", "-r", apk_path)
        return rc == 0

    async def extract_session(
        self,
        device_id: str,
        app_package: str = "com.spotify.music",
        output_dir: str = "/data/sessions"
    ) -> Optional[str]:
        """Extract session data from device and persist to local storage.

        Returns:
            Path to the extracted session directory on success, None on failure.
        """
        if self.mock_mode:
            logger.info(f"MOCK ADB: extract_session {device_id} {app_package}")
            return f"{output_dir}/{device_id.replace(':', '_')}/session"

        try:
            # Create output directory structure
            session_name = device_id.replace(":", "_")
            session_path = os.path.join(output_dir, session_name, "session")
            os.makedirs(session_path, exist_ok=True)

            # Define app data paths to extract
            data_paths = [
                f"/data/data/{app_package}/shared_prefs",
                f"/data/data/{app_package}/databases",
                f"/data/data/{app_package}/files",
            ]

            extracted_any = False
            for data_path in data_paths:
                # Check if path exists on device
                rc, _, _ = await self._run_adb(
                    "-s", device_id, "shell", f"test -d {data_path} && echo exists"
                )
                if rc != 0:
                    logger.debug(f"Path {data_path} does not exist on {device_id}")
                    continue

                # Pull data from device
                local_subdir = os.path.join(session_path, os.path.basename(data_path))
                os.makedirs(local_subdir, exist_ok=True)

                rc, stdout, stderr = await self._run_adb(
                    "-s", device_id, "pull", data_path, local_subdir
                )
                if rc == 0:
                    extracted_any = True
                    logger.debug(f"Extracted {data_path} from {device_id}")
                else:
                    logger.warning(f"Failed to extract {data_path} from {device_id}: {stderr}")

            if extracted_any:
                logger.info(f"Session extracted from {device_id} to {session_path}")
                return session_path
            else:
                logger.error(f"No session data could be extracted from {device_id}")
                return None

        except Exception as e:
            logger.error(f"Session extraction failed for {device_id}: {e}")
            return None

    async def inject_session(
        self,
        device_id: str,
        app_package: str = "com.spotify.music",
        session_dir: str = "/data/sessions"
    ) -> bool:
        """Inject session data into device from persisted storage.

        Args:
            device_id: ADB device identifier (e.g., "localhost:5555")
            app_package: Package name of the target app
            session_dir: Path to the session directory (as returned by extract_session)

        Returns:
            True on success, False on failure.
        """
        if self.mock_mode:
            logger.info(f"MOCK ADB: inject_session {device_id} {app_package}")
            return True

        try:
            if not os.path.isdir(session_dir):
                logger.error(f"Session directory does not exist: {session_dir}")
                return False

            # Ensure app is stopped before injecting session
            await self.force_stop(device_id, app_package)
            await asyncio.sleep(1)

            # Clear existing app data
            rc, _, stderr = await self._run_adb(
                "-s", device_id, "shell", f"pm clear {app_package}"
            )
            if rc != 0:
                logger.warning(f"Failed to clear app data for {app_package}: {stderr}")

            # Push session data to device
            injected_any = False
            subdirs = ["shared_prefs", "databases", "files"]

            for subdir in subdirs:
                local_path = os.path.join(session_dir, subdir)
                if not os.path.isdir(local_path):
                    continue

                device_path = f"/data/data/{app_package}/{subdir}"

                # Create directory on device
                await self._run_adb(
                    "-s", device_id, "shell", f"mkdir -p {device_path}"
                )

                # Push files
                rc, stdout, stderr = await self._run_adb(
                    "-s", device_id, "push", local_path, os.path.dirname(device_path)
                )
                if rc == 0:
                    injected_any = True
                    logger.debug(f"Injected {subdir} into {device_id}")
                else:
                    logger.warning(f"Failed to inject {subdir} into {device_id}: {stderr}")

            # Set correct permissions
            await self._run_adb(
                "-s", device_id, "shell", f"chown -R system:system /data/data/{app_package}"
            )
            await self._run_adb(
                "-s", device_id, "shell", f"chmod -R 755 /data/data/{app_package}"
            )

            if injected_any:
                logger.info(f"Session injected into {device_id} from {session_dir}")
                return True
            else:
                logger.error(f"No session data could be injected into {device_id}")
                return False

        except Exception as e:
            logger.error(f"Session injection failed for {device_id}: {e}")
            return False

    async def tap(self, device_id: str, x: int, y: int) -> bool:
        """Send tap event."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: tap {device_id} ({x}, {y})")
            return True
        rc, _, _ = await self._run_adb("-s", device_id, "shell", "input", "tap", str(x), str(y))
        return rc == 0

    async def send_keyevent(self, device_id: str, keycode: int) -> bool:
        """Send key event."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: keyevent {device_id} {keycode}")
            return True
        rc, _, _ = await self._run_adb("-s", device_id, "shell", "input", "keyevent", str(keycode))
        return rc == 0

    async def get_screen_xml(self, device_id: str) -> str:
        """Dump UI hierarchy XML."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: get_screen_xml {device_id}")
            return "<mock>ui hierarchy</mock>"
        # Dump UI XML on device then read it
        await self._run_adb("-s", device_id, "shell", "uiautomator", "dump", "/sdcard/window_dump.xml")
        rc, stdout, _ = await self._run_adb("-s", device_id, "shell", "cat", "/sdcard/window_dump.xml")
        if rc == 0 and stdout.strip():
            return stdout
        return ""

    async def is_app_running(self, device_id: str, package: str = "com.spotify.music") -> bool:
        """Check if app is in foreground."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: is_app_running {device_id} {package}")
            return True
        rc, stdout, _ = await self._run_adb("-s", device_id, "shell", "pidof", package)
        return rc == 0 and stdout.strip() != ""

    async def launch_app(self, device_id: str, package: str = "com.spotify.music") -> bool:
        """Launch an app."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: launch_app {device_id} {package}")
            return True
        rc, _, _ = await self._run_adb(
            "-s", device_id, "shell",
            "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"
        )
        return rc == 0

    async def launch_url(self, device_id: str, url: str) -> bool:
        """Launch a URL on the device using ACTION_VIEW."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: launch_url {device_id} {url[:80]}")
            return True
        rc, _, _ = await self._run_adb(
            "-s", device_id, "shell",
            "am", "start", "-a", "android.intent.action.VIEW", "-d", url
        )
        return rc == 0

    async def force_stop(self, device_id: str, package: str = "com.spotify.music") -> bool:
        """Force stop an app."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: force_stop {device_id} {package}")
            return True
        rc, _, _ = await self._run_adb("-s", device_id, "shell", "am", "force-stop", package)
        return rc == 0

    async def input_text(self, device_id: str, text: str) -> bool:
        """Input text."""
        if self.mock_mode:
            logger.info(f"MOCK ADB: input_text {device_id} '{text[:20]}...'")
            return True
        # Escape spaces for adb input
        escaped = text.replace(" ", "%s")
        rc, _, _ = await self._run_adb("-s", device_id, "shell", "input", "text", escaped)
        return rc == 0

    async def send_shell_command(self, device_id: str, command: str) -> tuple[int, str, str]:
        """Execute a raw shell command on the device.

        Returns (returncode, stdout, stderr) for caller to interpret.
        """
        if self.mock_mode:
            logger.info(f"MOCK ADB: send_shell_command {device_id} '{command[:50]}...'")
            return (0, "mock output", "")
        return await self._run_adb("-s", device_id, "shell", command)

    async def take_screenshot(self, device_id: str, output_path: str) -> Optional[str]:
        """Capture a screenshot from the device and save it to output_path.

        Returns the saved file path, or None on failure.
        """
        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        except Exception:
            pass

        if self.mock_mode:
            logger.info(f"MOCK ADB: take_screenshot {device_id} -> {output_path}")
            # Write a placeholder SVG so frontend <img> can render something
            svg_path = output_path.rsplit(".", 1)[0] + ".svg" if "." in output_path else output_path + ".svg"
            placeholder_svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="640" '
                'viewBox="0 0 360 640">'
                '<rect width="360" height="640" fill="#1a1a2e"/>'
                '<text x="180" y="300" text-anchor="middle" fill="#e94560" '
                'font-family="sans-serif" font-size="20">Challenge Screenshot</text>'
                '<text x="180" y="340" text-anchor="middle" fill="#aaa" '
                'font-family="sans-serif" font-size="14">(mock mode)</text>'
                '</svg>'
            )
            try:
                with open(svg_path, "w", encoding="utf-8") as f:
                    f.write(placeholder_svg)
                return svg_path
            except Exception as e:
                logger.warning(f"Failed to write mock screenshot: {e}")
                return None

        # Real mode: use exec-out screencap -p
        try:
            proc = await asyncio.create_subprocess_exec(
                "adb", "-s", device_id, "exec-out", "screencap", "-p",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            if proc.returncode == 0 and stdout_bytes:
                with open(output_path, "wb") as f:
                    f.write(stdout_bytes)
                return output_path
            else:
                logger.warning(f"screencap failed: {stderr_bytes.decode(errors='replace')}")
                return None
        except Exception as e:
            logger.error(f"Screenshot capture error: {e}")
            return None
