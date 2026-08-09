import analysis_core
from website_publish import publish_website


if __name__ == "__main__":
    analysis_core.main()
    try:
        publish_website()
    except RuntimeError as exc:
        raise SystemExit(f"\nWebsite publishing stopped: {exc}") from None
