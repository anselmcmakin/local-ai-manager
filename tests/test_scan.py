from conftest import load
def test_scan_readonly_and_shape(home):
    s = load("scan").scan(str(home))
    assert {"os", "disk_free_gb", "hardware", "tools"} <= s.keys()
    for c in load("scan").CMDS.values():
        for cmd in c: assert not any(w in " ".join(cmd) for w in ("rm ", "del ", "Remove-", "Set-", "install"))
