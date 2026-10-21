import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import cellcoach
print("CC311 truthy:", bool(cellcoach.CC311))
print("CC311 module file:", getattr(cellcoach.CC311, "__file__", None))
