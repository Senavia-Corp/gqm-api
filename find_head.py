import os
import re

versions_dir = "migrations/versions"
files = [f for f in os.listdir(versions_dir) if f.endswith('.py')]

revisions = set()
down_revisions = set()

for f in files:
    with open(os.path.join(versions_dir, f)) as file:
        content = file.read()
        rev_match = re.search(r"revision.*?['\"]([^'\"]+)['\"]", content)
        if rev_match:
            revisions.add(rev_match.group(1))
        
        down_match = re.search(r"down_revision.*?['\"]([^'\"]+)['\"]", content)
        if down_match:
            down_revisions.add(down_match.group(1))

heads = revisions - down_revisions
print("HEADS:", heads)
