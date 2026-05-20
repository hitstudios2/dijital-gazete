"""
Hit Studios - Otomatik Haber Üretici v5
Groq API (llama-3.1-8b-instant) — 14.400 istek/gün ücretsiz
Her haber üretildiğinde anında Firebase'e yazar.
"""

import os, json, time, random, base64, hashlib, datetime
import xml.etree.ElementTree as ET
import requests

# ─── AYARLAR ────────────────────────────────────────────────────────────────
HABER_SAYISI = 10
MAX_HABER    = 30
GROQ_MODEL   = "llama-3.1-8b-instant"
RETRY_LIMIT  = 3
RETRY_WAIT   = 5

RSS_SOURCES = [
    "https://news.google.com/rss/search?q=yapay+zeka&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=teknoloji+yazilim&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=siber+guvenlik&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=mobil+uygulama&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=startup+turkiye&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=artificial+intelligence+2025&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=blockchain+kripto&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=cloud+computing+technology&hl=tr&gl=TR&ceid=TR%3Atr",
]

KATEGORILER = [
    "Yapay Zeka",
    "Donanım",
    "Yazılım",
    "Sosyal Medya",
    "Siber Güvenlik",
    "Teknoloji",
]
# ─────────────────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def rss_haberleri_cek():
    haberler = []
    for url in RSS_SOURCES:
        try:
            r = requests.get(url, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            })
            r.encoding = "utf-8"
            root  = ET.fromstring(r.text)
            items = root.findall(".//item")
            for item in items:
                baslik = item.findtext("title", "").strip()
                link   = item.findtext("link",  "").strip()
                if baslik and link and len(baslik) > 10:
                    haberler.append({"baslik": baslik, "link": link})
            log(f"RSS OK: {url[:55]}... ({len(items)} haber)")
        except Exception as e:
            log(f"RSS HATA: {e}")

    gorulmus, benzersiz = set(), []
    random.shuffle(haberler)
    for h in haberler:
        k = h["baslik"][:60].lower()
        if k not in gorulmus:
            gorulmus.add(k)
            benzersiz.append(h)
    log(f"Toplam benzersiz haber: {len(benzersiz)}")
    return benzersiz

def groq_iste(sistem, kullanici, api_key, max_tokens=1500):
    """Groq API'ye istek at."""
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": sistem},
                {"role": "user",   "content": kullanici}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7
        },
        timeout=60
    )
    if not r.ok:
        raise Exception(f"Groq HTTP {r.status_code}: {r.text[:300]}")
    metin = r.json()["choices"][0]["message"]["content"].strip()
    # ```html bloğunu temizle
    if "```" in metin:
        parcalar = metin.split("```")
        metin = parcalar[1] if len(parcalar) > 1 else parcalar[0]
        if metin.lower().startswith("html"):
            metin = metin[4:]
    return metin.strip()

def haber_uret(baslik, api_key):
    """Tek Groq isteğiyle makale + özet + kategori üret (JSON)."""
    sistem = "Sen Hit Studios'un teknoloji editörüsün. Verilen haber başlığından Türkçe içerik üretiyorsun."
    kullanici = f"""Aşağıdaki haber başlığı için şunları üret ve SADECE JSON formatında döndür, başka hiçbir şey yazma:

Haber Başlığı: {baslik}

JSON formatı (tam olarak bu şekilde):
{{
  "ozet": "tek cümlelik dikkat çekici Türkçe özet",
  "kategori": "Teknoloji",
  "icerik": "<p>paragraf 1</p><h3>Bölüm Başlığı</h3><p>paragraf 2</p><p>paragraf 3</p>"
}}

Kategori seçim kuralı:
- Haber yapay zeka, makine öğrenmesi, ChatGPT, Gemini, LLM ile ilgiliyse: "Yapay Zeka"
- Haber telefon, tablet, bilgisayar, chip, ekran, cihaz, donanım ile ilgiliyse: "Donanım"
- Haber yazılım, uygulama, kod, platform, güncelleme, işletim sistemi ile ilgiliyse: "Yazılım"
- Haber Instagram, TikTok, Twitter/X, YouTube, Facebook, sosyal ağ ile ilgiliyse: "Sosyal Medya"
- Haber hack, siber saldırı, güvenlik açığı, veri ihlali, fidye yazılımı ile ilgiliyse: "Siber Güvenlik"
- Diğer tüm teknoloji haberleri için: "Teknoloji"
- kategori alanına SADECE şu 6 değerden birini yaz: Yapay Zeka, Donanım, Yazılım, Sosyal Medya, Siber Güvenlik, Teknoloji

icerik kuralları:
- 3-4 paragraf, HTML formatında
- <p> ve <h3> etiketleri kullan
- Türkçe yaz, doğal ve akıcı olsun

SADECE JSON döndür, başka hiçbir şey yazma."""

    metin = groq_iste(sistem, kullanici, api_key, 1500)

    # JSON'u parse et
    try:
        # Bazen model { } dışında metin ekleyebilir, temizle
        if "{" in metin and "}" in metin:
            start = metin.index("{")
            end   = metin.rindex("}") + 1
            metin = metin[start:end]
        data = json.loads(metin)
        ozet     = data.get("ozet", "")
        kategori = data.get("kategori", "Teknoloji")
        icerik   = data.get("icerik", "")
        # Kategori geçerliyse kullan, değilse varsayılan
        if kategori not in KATEGORILER:
            kategori = "Teknoloji"
        return ozet, kategori, icerik
    except Exception as e:
        log(f"  JSON parse hatası: {e} — ham metin: {metin[:100]}")
        raise Exception(f"JSON parse hatası: {e}")

def get_access_token(service_account_json):
    sa = json.loads(service_account_json)
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    private_key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    now     = int(time.time())
    header  = base64.urlsafe_b64encode(json.dumps({"alg":"RS256","typ":"JWT"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/datastore",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600, "iat": now
    }).encode()).rstrip(b"=")
    signing_input = header + b"." + payload
    sig = base64.urlsafe_b64encode(
        private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    ).rstrip(b"=")
    jwt_token = (signing_input + b"." + sig).decode()
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt_token
    })
    if not r.ok:
        raise Exception(f"Token alınamadı: {r.text}")
    return r.json()["access_token"]

def firebase_oku(project_id, token):
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/hit_data/gazete"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if not r.ok:
            return []
        data = r.json()
        vals = data.get("fields",{}).get("items",{}).get("arrayValue",{}).get("values",[])
        return [{k: list(v.values())[0] for k,v in item.get("mapValue",{}).get("fields",{}).items()} for item in vals]
    except Exception as e:
        log(f"Firebase okuma: {e}")
        return []

def temizle(s):
    """Firebase için string temizle."""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("\x00", "").replace("\r", "")

def firebase_yaz(project_id, token, haberler):
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/hit_data/gazete"
    
    def to_fs(h):
        fields = {}
        for k, v in h.items():
            v_str = temizle(v)
            # icerik alanını base64 ile sakla (HTML özel karakterler sorun çıkarmasın)
            if k == "icerik":
                v_str = base64.b64encode(v_str.encode("utf-8")).decode("ascii")
            fields[k] = {"stringValue": v_str}
        return {"mapValue": {"fields": fields}}
    
    body = {"fields": {"items": {"arrayValue": {"values": [to_fs(h) for h in haberler]}}}}
    
    # JSON'u manuel encode et
    body_str = json.dumps(body, ensure_ascii=True)
    
    r = requests.patch(
        url, 
        data=body_str.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }, 
        timeout=30
    )
    if not r.ok:
        raise Exception(f"Firebase yazma hatası: {r.status_code} {r.text[:300]}")

def haber_id(baslik):
    return hashlib.md5(baslik.encode("utf-8")).hexdigest()[:12]

def tarih_tr():
    aylar = ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran",
             "Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"]
    d = datetime.datetime.now()
    return f"{d.day} {aylar[d.month-1]} {d.year}"

def main():
    log("=" * 50)
    log("Hit Studios Haber Üretici v5 (Groq) Başladı")
    log("=" * 50)

    groq_key   = os.environ.get("GROQ_API_KEY", "")
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "hit-studios-web-2231e")
    fb_key_b64 = os.environ.get("FIREBASE_KEY", "")

    if not groq_key or not fb_key_b64:
        log("HATA: GROQ_API_KEY veya FIREBASE_KEY eksik!")
        return

    # Groq testi
    log("Groq bağlantısı test ediliyor...")
    try:
        test = groq_iste("Sen bir asistansın.", "Sadece 'OK' yaz.", groq_key, 10)
        log(f"Groq OK: {test[:20]}")
    except Exception as e:
        log(f"Groq bağlantı HATA: {e}")
        return

    # Firebase bağlantısı
    try:
        token = get_access_token(base64.b64decode(fb_key_b64).decode("utf-8"))
        log("Firebase bağlantısı kuruldu.")
    except Exception as e:
        log(f"Firebase auth HATA: {e}")
        return

    # Mevcut haberleri oku
    mevcut    = firebase_oku(project_id, token)
    var_idler = {h.get("id","") for h in mevcut}
    log(f"Mevcut haber sayısı: {len(mevcut)}")

    # RSS'ten haber çek
    rss = rss_haberleri_cek()
    if not rss:
        log("RSS'ten haber gelmedi, çıkılıyor.")
        return

    # Haberleri üret — her başarılı haberden sonra anında Firebase'e yaz
    sayac = 0
    for rss_h in rss:
        if sayac >= HABER_SAYISI:
            break

        hid = haber_id(rss_h["baslik"])
        if hid in var_idler:
            log(f"Atlandı (zaten var): {rss_h['baslik'][:45]}...")
            continue

        log(f"[{sayac+1}/{HABER_SAYISI}] Üretiliyor: {rss_h['baslik'][:55]}...")

        basari = False
        for deneme in range(RETRY_LIMIT):
            try:
                ozet, kategori, icerik = haber_uret(rss_h["baslik"], groq_key)
                basari = True
                break
            except Exception as e:
                log(f"  Hata deneme {deneme+1}/{RETRY_LIMIT}: {e}")
                if deneme < RETRY_LIMIT - 1:
                    time.sleep(RETRY_WAIT)

        if not basari:
            log(f"  Atlandı (üretilemedi)")
            continue

        # Anında Firebase'e yaz
        yeni_haber = {
            "id":       hid,
            "baslik":   rss_h["baslik"],
            "ozet":     ozet,
            "icerik":   icerik,
            "kategori": kategori,
            "tarih":    tarih_tr(),
            "kaynak":   rss_h["link"]
        }

        mevcut.insert(0, yeni_haber)
        mevcut = mevcut[:MAX_HABER]
        var_idler.add(hid)

        try:
            firebase_yaz(project_id, token, mevcut)
            log(f"  ✓ Firebase'e yazıldı. (Toplam: {len(mevcut)} haber)")
        except Exception as e:
            log(f"  Firebase yazma HATA: {e}")

        sayac += 1
        time.sleep(4)  # TPM limiti aşmamak için

    log(f"Tamamlandı! Üretilen: {sayac} haber. Firebase'de toplam: {len(mevcut)} haber.")
    log("=" * 50)

if __name__ == "__main__":
    main()
