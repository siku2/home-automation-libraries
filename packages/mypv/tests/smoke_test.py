"""Check that basic features work.

Catch cases where e.g. files are missing so the import doesn't work. It is
recommended to check that e.g. assets are included.

This is used by the publish.yaml workflow to check the built package.
"""

import mypv.acthor
import mypv.cli
import mypv.discovery

_ = mypv.acthor, mypv.cli, mypv.discovery
