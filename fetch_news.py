"""
Hit Studios - Otomatik Haber Üretici v6
- Her kategoriden 2 haber üretir (6 kategori × 2 = 12 haber/çalışma)
- Kategori ayrı istek ile belirlenir (daha doğru)
- Firebase'de max 48 haber tutulur
- Başlıklardan kaynak site adı temizlenir
- Her haber üretilince anında Firebase'e yazılır
"""

import os, json, time, random, base64, hashlib, datetime, re
import xml.etree.ElementTree as ET
import requests

# ─── AYARLAR ────────────────────────────────────────────────────────────────
KATEGORI_BASI_HABER = 2       # Her kategoriden kaç haber
MAX_HABER           = 48      # Firebase'de max haber sayısı
GROQ_MODEL          = "llama-3.1-8b-instant"
RETRY_LIMIT         = 3
RETRY_WAIT          = 8

KATEGORILER = [
    "Yapay Zeka",
    "Donanım",
    "Yazılım",
    "Sosyal Medya",
    "Siber Güvenlik",
    "Teknoloji",
]

# Kategori başına RSS kaynakları — en alakalı haberler üstte gelir
KATEGORI_RSS = {
    "Yapay Zeka":    [
        "https://news.google.com/rss/search?q=yapay+zeka+AI&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=chatgpt+gemini+yapay+zeka&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Donanım":       [
        "https://news.google.com/rss/search?q=iphone+samsung+telefon+donanim&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=bilgisayar+chip+gpu+cihaz&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Yazılım":       [
        "https://news.google.com/rss/search?q=yazilim+uygulama+guncelleme&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=mobil+uygulama+platform&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Sosyal Medya":  [
        "https://news.google.com/rss/search?q=instagram+tiktok+twitter+sosyal+medya&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=youtube+facebook+sosyal+ag&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Siber Güvenlik":[
        "https://news.google.com/rss/search?q=siber+guvenlik+hack+saldiri&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=veri+ihlali+fidye+yazilim&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Teknoloji":     [
        "https://news.google.com/rss/search?q=teknoloji+girisim+startup&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=blockchain+kripto+fintech&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
}
# ─────────────────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def baslik_temizle(baslik):
    """Başlıktan '- Site Adı' veya '| Site Adı' formatını kaldır."""
    temiz = re.sub(r'\s*[-|]\s*[^-|]{3,50}$', '', baslik).strip()
    return temiz if temiz else baslik

def rss_cek(url):
    """Tek bir RSS URL'sinden haberleri çek."""
    try:
        r = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })
        r.encoding = "utf-8"
        root  = ET.fromstring(r.text)
        items = root.findall(".//item")
        haberler = []
        for item in items:
            baslik = item.findtext("title", "").strip()
            link   = item.findtext("link",  "").strip()
            if baslik and link and len(baslik) > 10:
                haberler.append({"baslik": baslik_temizle(baslik), "link": link})
        return haberler
    except Exception as e:
        log(f"  RSS HATA ({url[:50]}...): {e}")
        return []

def groq_iste(sistem, kullanici, api_key, max_tokens=1500):
    """Groq API'ye istek at, retry mantığı ile."""
    for deneme in range(RETRY_LIMIT):
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
                hata = r.text
                # TPM limitine takıldıysak bekleme süresini oku
                eslesme = re.search(r'try again in (\d+\.?\d*)s', hata)
                bekle = float(eslesme.group(1)) + 1 if eslesme else RETRY_WAIT
                raise Exception(f"HTTP {r.status_code} — bekle {bekle:.1f}s: {hata[:100]}")

            metin = r.json()["choices"][0]["message"]["content"].strip()
            # ```...``` bloğunu temizle
            if "```" in metin:
                parcalar = metin.split("```")
                metin = parcalar[1] if len(parcalar) > 1 else parcalar[0]
                if metin.lower().startswith(("html", "json")):
                    metin = metin.split("\n", 1)[-1]
            return metin.strip()

        except Exception as e:
            log(f"    Groq hata deneme {deneme+1}/{RETRY_LIMIT}: {str(e)[:100]}")
            if deneme < RETRY_LIMIT - 1:
                eslesme = re.search(r'bekle (\d+\.?\d*)s', str(e))
                bekle = float(eslesme.group(1)) if eslesme else RETRY_WAIT
                time.sleep(min(bekle, 30))
            else:
                raise

def kategori_belirle(baslik, api_key):
    """Haber başlığına göre kategori belirle — ayrı istek."""
    sistem = "Sen bir teknoloji editörüsün. Verilen haber başlığı için en uygun kategoriyi seçiyorsun."
    kullanici = f"""Haber başlığı: {baslik}

Sadece aşağıdaki 6 kategoriden birini yaz, başka hiçbir şey yazma:

Yapay Zeka → ChatGPT, Gemini, yapay zeka modeli, LLM, AI
Donanım → iPhone, Samsung, telefon, tablet, bilgisayar, chip, GPU, ekran, cihaz
Yazılım → uygulama, güncelleme, kod, platform, işletim sistemi, API, yazılım
Sosyal Medya → Instagram, TikTok, Twitter, X, YouTube, Facebook, sosyal ağ
Siber Güvenlik → hack, siber saldırı, virüs, fidye, veri ihlali, güvenlik açığı
Teknoloji → yukarıdakilerin dışındaki teknoloji haberleri

Cevap (sadece kategori adı):"""

    sonuc = groq_iste(sistem, kullanici, api_key, 20).strip()
    # Tam eşleşme
    if sonuc in KATEGORILER:
        return sonuc
    # Kısmi eşleşme
    for k in KATEGORILER:
        if k.lower() in sonuc.lower():
            return k
    return "Teknoloji"

def makale_uret(baslik, api_key):
    """Haber başlığından makale ve özet üret."""
    sistem = "Sen Hit Studios'un teknoloji editörüsün. Profesyonel, akıcı Türkçe teknoloji makaleleri yazıyorsun."
    kullanici = f"""Şu haber başlığından yola çıkarak SADECE JSON döndür:

Haber: {baslik}

JSON:
{{
  "ozet": "tek cümlelik dikkat çekici Türkçe özet",
  "icerik": "<p>paragraf 1</p><h3>Başlık</h3><p>paragraf 2</p><p>paragraf 3</p>"
}}

Kurallar:
- ozet: tek cümle, merak uyandırsın
- icerik: 3-4 paragraf, <p> ve <h3> etiketleri, Türkçe
- SADECE JSON döndür"""

    metin = groq_iste(sistem, kullanici, api_key, 1200)
    # JSON parse
    if "{" in metin and "}" in metin:
        start = metin.index("{")
        end   = metin.rindex("}") + 1
        metin = metin[start:end]
    data   = json.loads(metin)
    ozet   = data.get("ozet", "")
    icerik = data.get("icerik", "")
    return ozet, icerik

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
    if not isinstance(s, str):
        s = str(s)
    return s.replace("\x00", "").replace("\r", "")

def firebase_yaz(project_id, token, haberler):
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/hit_data/gazete"
    def to_fs(h):
        fields = {}
        for k, v in h.items():
            v_str = temizle(v)
            if k == "icerik":
                v_str = base64.b64encode(v_str.encode("utf-8")).decode("ascii")
            fields[k] = {"stringValue": v_str}
        return {"mapValue": {"fields": fields}}
    body = {"fields": {"items": {"arrayValue": {"values": [to_fs(h) for h in haberler]}}}}
    body_str = json.dumps(body, ensure_ascii=True)
    r = requests.patch(url, data=body_str.encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=30)
    if not r.ok:
        raise Exception(f"Firebase yazma hatası: {r.status_code} {r.text[:200]}")

def haber_id(baslik):
    return hashlib.md5(baslik.encode("utf-8")).hexdigest()[:12]

def tarih_tr():
    aylar = ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran",
             "Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"]
    d = datetime.datetime.now()
    return f"{d.day} {aylar[d.month-1]} {d.year}"

def main():
    log("=" * 55)
    log("Hit Studios Haber Üretici v6 Başladı")
    log(f"Hedef: Her kategoriden {KATEGORI_BASI_HABER} haber = {len(KATEGORILER)*KATEGORI_BASI_HABER} haber")
    log("=" * 55)

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
        log(f"Groq HATA: {e}"); return

    # Firebase bağlantısı
    try:
        token = get_access_token(base64.b64decode(fb_key_b64).decode("utf-8"))
        log("Firebase bağlantısı kuruldu.")
    except Exception as e:
        log(f"Firebase auth HATA: {e}"); return

    # Mevcut haberleri oku
    mevcut    = firebase_oku(project_id, token)
    var_idler = {h.get("id","") for h in mevcut}
    log(f"Mevcut haber sayısı: {len(mevcut)}")

    # Her kategoriden haber üret
    toplam_uretilen = 0

    for kategori in KATEGORILER:
        log(f"\n── {kategori} ──")
        kategori_sayac = 0
        rss_urls = KATEGORI_RSS.get(kategori, [])

        # Bu kategorinin RSS'lerinden haberleri çek
        aday_haberler = []
        for url in rss_urls:
            haberler = rss_cek(url)
            log(f"  RSS: {len(haberler)} haber çekildi")
            aday_haberler.extend(haberler)

        # Tekrarları kaldır
        gorulmus = set()
        benzersiz = []
        for h in aday_haberler:
            k = h["baslik"][:60].lower()
            if k not in gorulmus:
                gorulmus.add(k)
                benzersiz.append(h)

        log(f"  Benzersiz aday: {len(benzersiz)}")

        # Bu kategoriden KATEGORI_BASI_HABER kadar haber üret
        for rss_h in benzersiz:
            if kategori_sayac >= KATEGORI_BASI_HABER:
                break

            hid = haber_id(rss_h["baslik"])
            if hid in var_idler:
                log(f"  Atlandı (zaten var): {rss_h['baslik'][:40]}...")
                continue

            log(f"  [{kategori_sayac+1}/{KATEGORI_BASI_HABER}] Üretiliyor: {rss_h['baslik'][:50]}...")

            try:
                # 1. Makale ve özet üret
                ozet, icerik = makale_uret(rss_h["baslik"], groq_key)
                time.sleep(2)
                # 2. Kategoriyi ayrı istek ile doğrula
                gercek_kategori = kategori_belirle(rss_h["baslik"], groq_key)
                log(f"     Kategori: {gercek_kategori}")

            except Exception as e:
                log(f"  Hata (atlandı): {e}")
                continue

            yeni_haber = {
                "id":       hid,
                "baslik":   rss_h["baslik"],
                "ozet":     ozet,
                "icerik":   icerik,
                "kategori": gercek_kategori,
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

            kategori_sayac  += 1
            toplam_uretilen += 1
            time.sleep(3)

        log(f"  {kategori}: {kategori_sayac} haber üretildi.")

    log(f"\n{'='*55}")
    log(f"Tamamlandı! Üretilen: {toplam_uretilen} haber. Firebase'de toplam: {len(mevcut)} haber.")
    log("=" * 55)

if __name__ == "__main__":
    main()
