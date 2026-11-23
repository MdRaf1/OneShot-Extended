# Ensures the repo root is on sys.path for `import src.xxx` in tests,
# since src/ has no __init__.py (namespace package, matching the
# existing style used by ose.py and friends).
