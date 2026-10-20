# Runs the ComicTagger installed from requirements.txt. Issuarr calls this as a separate
# process (mylar/cmtagmylar.py) so tagging can't take the web server down with it.
import sys

from comictaggerlib.main import main

if __name__ == '__main__':
    sys.exit(main())
