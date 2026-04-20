FROM alpine:3.19

RUN apk add --no-cache redsocks iptables curl bash gettext-envsubst

COPY redsocks.conf.tmpl /etc/redsocks.conf.tmpl
COPY entrypoint.sh /entrypoint.sh
COPY reload.sh /reload.sh

RUN chmod +x /entrypoint.sh /reload.sh

ENTRYPOINT ["/entrypoint.sh"]
