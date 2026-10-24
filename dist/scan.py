# Local AI Manager hardware scan v0.1.0. Read-only: runs a fixed list of query commands and prints JSON.
import json, os, platform, shutil, subprocess, sys
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # no console flash on Windows

CMDS = {
    "Windows": [["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,driver_version,temperature.gpu,utilization.gpu", "--format=csv,noheader"],
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", "Get-CimInstance Win32_VideoController | Select Name,DriverVersion | ConvertTo-Json"],
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", "Get-CimInstance Win32_Processor | Select Name,NumberOfCores | ConvertTo-Json"],
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"],
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", "Get-PSDrive -PSProvider FileSystem | Select Name,Free,Used | ConvertTo-Json"],
                ["wsl", "--status"]],
    "Darwin":  [["sysctl", "-n", "machdep.cpu.brand_string", "hw.memsize"],
                ["system_profiler", "SPHardwareDataType", "SPDisplaysDataType"]],
    "Linux":   [["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,driver_version,temperature.gpu,utilization.gpu", "--format=csv,noheader"],
                ["rocm-smi", "--showproductname", "--showmeminfo", "vram"],
                ["lscpu"], ["free", "-g"]],
}
TOOLS = [["ollama", "-v"], ["ollama", "list"], ["ollama", "ps"], ["lms", "version"], ["llama-server", "--version"],
         ["python3", "--version"], ["python", "--version"], ["py", "-3", "--version"], ["docker", "--version"]]

def run(cmd, timeout=20):
    if not shutil.which(cmd[0]):
        return {"cmd": " ".join(cmd), "missing": True}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=timeout)
        return {"cmd": " ".join(cmd), "rc": r.returncode, "out": (r.stdout or r.stderr)[:4000]}
    except Exception as e:
        return {"cmd": " ".join(cmd), "error": str(e)}

def scan(home="~"):
    osname = platform.system()
    du = shutil.disk_usage(os.path.expanduser(home))
    return {"os": osname, "release": platform.release(), "machine": platform.machine(),
            "disk_free_gb": round(du.free / 1e9, 1), "disk_total_gb": round(du.total / 1e9, 1),
            "hardware": [run(c) for c in CMDS.get(osname, [])], "tools": [run(c) for c in TOOLS]}

if __name__ == "__main__":
    json.dump(scan(), sys.stdout, indent=2)
