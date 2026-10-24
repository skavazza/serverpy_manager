import os
import sys

# Add src to python path if running as a script
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gui.controller import AppController

def main():
    """
    Main entry point for ServerPy.
    """
    try:
        if '--autostart' in sys.argv and not getattr(sys, 'frozen', False):
            os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        controller = AppController()
        controller.run()
    except KeyboardInterrupt:
        print("\nApplication closed by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Critical Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
