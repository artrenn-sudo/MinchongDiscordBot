import py_compile
import sys

files = ['main.py', 'cogs/music.py', 'cogs/fun.py', 'cogs/general.py', 'cogs/utilities.py']
ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"OK: {f}")
    except py_compile.PyCompileError as e:
        print(f"ERROR: {f}: {e}")
        ok = False

if ok:
    print("ALL FILES PASSED SYNTAX CHECK")
else:
    print("SOME FILES FAILED")
    sys.exit(1)
