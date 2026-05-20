"""
Hit Studios - Otomatik Haber Üretici v2
"""

import os, json, time, random, base64, hashlib, datetime
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET

# ─── AYARLAR ────────────────────────────────────────────────────────────────
HABER_SAYISI = 10
MAX_HABER    = 30
GEMINI_MODEL = "gemini-2.5-flash"
RETRY_LIMIT  = 3
RETRY_WAIT   = 5

# Türkçe karakter içermeyen, encode güvenli URL'ler
RSS_SOURCES = [
    "https://news.google.com/rss/search?q=yapay+zeka&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=teknoloji+yazilim&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=siber+guvenlik&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=mobil+uygulama&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=startup+turkiye&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=artificial+intelligence&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=cybersecurity+2025&hl=tr&gl=TR&ceid=TR%3Atr",
    "https://news.google.com/rss/search?q=blockchain+kripto&hl=tr&gl=TR&ceid=TR%3Atr",
]

KATEGORILER = [
    "Teknoloji",
    "Yapay Zeka",
    "Mobil",
    "Siber Güvenlik",
    "Yazılım",
    "Donanım",
    "Girişim",
    "Oyun & Eğlence",
    "Bulut & Altyapı",
    "Blockchain & Kripto",
    "Veri & Analitik",
    "Robotik & Otomasyon",
    "Ar-Ge & İnovasyon",
    "E-Ticaret & Fintech",
    "Sosyal Medya",
    "Uzay & Bilim",
]
# ─────────────────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

def rss_haberleri_cek():
    haberler = []
    for url in RSS_SOURCES:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)",
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                    "Accept-Charset": "utf-8",
                }
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
            # Encoding'i zorla UTF-8 olarak çöz
            try:
                xml_data = raw.decode("utf-8")
            except UnicodeDecodeError:
                xml_data = raw.decode("latin-1")

            root  = ET.fromstring(xml_data)
            items = root.findall(".//item")
            for item in items:
                baslik = item.findtext("title", "").strip()
                link   = item.findtext("link",  "").strip()
                if baslik and link and len(baslik) > 10:
                    haberler.append({"baslik": baslik, "link": link})
            log(f"RSS OK: {url[:60]}... ({len(items)} haber)")
        except Exception as e:
            log(f"RSS HATA ({url[:40]}...): {e}")

    # Karıştır ve tekrarları kaldır
    gorulmus, benzersiz = set(), []
    random.shuffle(haberler)
    for h in haberler:
        k = h["baslik"][:60].lower()
        if k not in gorulmus:
            gorulmus.add(k)
            benzersiz.append(h)
    log(f"Toplam benzersiz haber: {len(benzersiz)}")
    return benzersiz

def gemini_iste(prompt, api_key, max_tokens=1200):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": max_tokens
        }
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    metin = data["candidates"][0]["content"]["parts"][0]["text"].strip()

    # ```html ... ``` bloğunu temizle
    if "```" in metin:
        parcalar = metin.split("```")
        metin = parcalar[1] if len(parcalar) > 1 else parcalar[0]
        if metin.lower().startswith("html"):
            metin = metin[4:]
    return metin.strip()

def kategori_belirle(baslik, api_key):
    """Gemini'ye başlığı okutup doğru kategoriyi seçtir."""
    liste = "\n".join(f"- {k}" for k in KATEGORILER)
    prompt = f"""Aşağıdaki haber başlığı için en uygun kategoriyi seç. Sadece kategori adını yaz, başka hiçbir şey ekleme.

Kategoriler:
{liste}

Haber başlığı: {baslik}"""
    try:
        k = gemini_iste(prompt, api_key, 30).strip()
        # Listede varsa kullan, yoksa random seç
        if k in KATEGORILER:
            return k
        # Kısmi eşleşme dene
        for kat in KATEGORILER:
            if kat.lower() in k.lower() or k.lower() in kat.lower():
                return kat
    except:
        pass
    return random.choice(KATEGORILER)

def makale_uret(baslik, api_key):
    return gemini_iste(f"""Sen Hit Studios'un teknoloji editörüsün. Aşağıdaki haber başlığından yola çıkarak profesyonel, akıcı, bilgilendirici bir Türkçe teknoloji makalesi yaz.

Haber Başlığı: {baslik}

Kurallar:
- 3-5 paragraf olsun
- Her paragraf <p>...</p> içinde olsun
- En az 1 bölüm başlığı ekle: <h3>...</h3>
- Gerekirse madde listesi: <ul><li>...</li></ul>
- Sadece HTML içeriği döndür, başka hiçbir şey yazma
- Türkçe yaz, doğal ve akıcı olsun
- Uydurma, mantıklı ve tutarlı yaz

Makaleyi yaz:""", api_key, 1200)

def ozet_uret(baslik, api_key):
    return gemini_iste(f"""Şu haber başlığı için tek cümlelik, dikkat çekici Türkçe bir özet yaz. Sadece özeti yaz, başka hiçbir şey ekleme.

Başlık: {baslik}""", api_key, 80)

def get_access_token(service_account_json):
    sa = json.loads(service_account_json)
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    private_key = serialization.load_pem_private_key(
        sa["private_key"].encode(), password=None
    )
    now     = int(time.time())
    header  = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps({
            "iss":   sa["client_email"],
            "scope": "https://www.googleapis.com/auth/datastore",
            "aud":   "https://oauth2.googleapis.com/token",
            "exp":   now + 3600,
            "iat":   now
        }).encode()
    ).rstrip(b"=")
    signing_input = header + b"." + payload
    sig = base64.urlsafe_b64encode(
        private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    ).rstrip(b"=")
    jwt = (signing_input + b"." + sig).decode()

    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion":  jwt
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]

def firebase_oku(project_id, token):
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/hit_data/gazete"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        vals = data.get("fields", {}).get("items", {}).get("arrayValue", {}).get("values", [])
        return [
            {k: list(v.values())[0] for k, v in item.get("mapValue", {}).get("fields", {}).items()}
            for item in vals
        ]
    except Exception as e:
        log(f"Firebase okuma (ilk çalışmada normal): {e}")
        return []

def firebase_yaz(project_id, token, haberler):
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/hit_data/gazete"

    def to_fs(h):
        return {"mapValue": {"fields": {k: {"stringValue": str(v)} for k, v in h.items()}}}

    body = json.dumps(
        {"fields": {"items": {"arrayValue": {"values": [to_fs(h) for h in haberler]}}}},
        ensure_ascii=False
    ).encode("utf-8")

    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        },
        method="PATCH"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    log(f"Firebase'e {len(haberler)} haber yazıldı.")

def haber_id(baslik):
    return hashlib.md5(baslik.encode("utf-8")).hexdigest()[:12]

def tarih_tr():
    aylar = ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran",
             "Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"]
    d = datetime.datetime.now()
    return f"{d.day} {aylar[d.month-1]} {d.year}"

def main():
    log("=" * 50)
    log("Hit Studios Haber Üretici v2 Başladı")
    log("=" * 50)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "hit-studios-web-2231e")
    fb_key_b64 = os.environ.get("FIREBASE_KEY", "")

    if not gemini_key or not fb_key_b64:
        log("HATA: GEMINI_API_KEY veya FIREBASE_KEY eksik!")
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
    var_idler = {h.get("id", "") for h in mevcut}
    log(f"Mevcut haber sayısı: {len(mevcut)}")

    # RSS'ten haber çek
    rss = rss_haberleri_cek()
    if not rss:
        log("RSS'ten haber gelmedi, çıkılıyor.")
        return

    # Haberleri üret
    yeniler, sayac = [], 0
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
                icerik   = makale_uret(rss_h["baslik"], gemini_key)
                ozet     = ozet_uret(rss_h["baslik"], gemini_key)
                kategori = kategori_belirle(rss_h["baslik"], gemini_key)
                basari   = True
                break
            except urllib.error.HTTPError as e:
                log(f"  HTTP {e.code} hatası deneme {deneme+1}: {e.reason}")
                if deneme < RETRY_LIMIT - 1:
                    time.sleep(RETRY_WAIT)
            except Exception as e:
                log(f"  Hata deneme {deneme+1}: {e}")
                if deneme < RETRY_LIMIT - 1:
                    time.sleep(RETRY_WAIT)

        if not basari:
            log(f"  Atlandı (üretilemedi)")
            continue

        yeniler.append({
            "id":       hid,
            "baslik":   rss_h["baslik"],
            "ozet":     ozet,
            "icerik":   icerik,
            "kategori": kategori,
            "tarih":    tarih_tr(),
            "kaynak":   rss_h["link"]
        })
        sayac += 1
        time.sleep(2)  # Rate limit koruması

    log(f"Üretilen yeni haber: {len(yeniler)}")

    if not yeniler:
        log("Yeni haber üretilemedi. Mevcut haberler korunuyor.")
        return

    # Yeniler başa, max 30 tut
    tum = (yeniler + mevcut)[:MAX_HABER]
    try:
        firebase_yaz(project_id, token, tum)
        log(f"Tamamlandı! Firebase'de toplam {len(tum)} haber.")
    except Exception as e:
        log(f"Firebase yazma HATA: {e}")

    log("=" * 50)

if __name__ == "__main__":
    main()
