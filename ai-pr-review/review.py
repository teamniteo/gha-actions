# a python file that writes "foo" into review.txt

from datetime import datetime

with open("review.txt", "w") as f:
    f.write(f"## AI Code Review\n\nfoo\n\n{datetime.now().isoformat()}")
