"""MusicHarbor command-line entry point."""
import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    if '--packaging-smoke' in sys.argv or '--window-smoke' in sys.argv:
        from tools.packaged_smoke import main as smoke
        try:
            smoke(window='--window-smoke' in sys.argv)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Packaged smoke check failed')
            raise SystemExit(1)
        return
    from musicharbor.desktop import main as desktop
    desktop()


if __name__ == '__main__':
    main()
