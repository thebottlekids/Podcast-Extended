import os

from waitress import serve

from app import create_web_app


def main() -> None:
    """Main entry point for the application."""
    app = create_web_app()

    # Start the application server
    threads_env = os.environ.get("SERVER_THREADS")
    try:
        threads = int(threads_env) if threads_env is not None else 1
    except ValueError:
        threads = 1

    port = os.environ.get("PORT", 5001)

    # waitress discards X-Forwarded-* from untrusted peers, so without this the
    # ProxyFix middleware never sees them and the login rate-limiter keys every
    # request on the reverse proxy's address instead of the real client's.
    # Set TRUSTED_PROXY_IP to the proxy's source address as seen by this
    # container (the diagnostics endpoint reports it as remote_addr).
    #
    # "*" trusts any peer -- only safe when nothing but the proxy can reach this
    # port, since any client that can connect could then spoof its own client IP.
    trusted_proxy = (os.environ.get("TRUSTED_PROXY_IP") or "").strip()
    if trusted_proxy:
        serve(
            app,
            host="0.0.0.0",
            port=port,
            threads=threads,
            trusted_proxy=trusted_proxy,
            trusted_proxy_headers={
                "x-forwarded-for",
                "x-forwarded-proto",
                "x-forwarded-host",
            },
        )
        return

    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=threads,
    )


if __name__ == "__main__":
    main()
