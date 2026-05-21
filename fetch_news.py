"""
Hit Studios - Otomatik Haber Üretici v7.1 (Zırhlı Ayrıştırma)
- Kategori RSS kaynağına göre direkt atanır
- Son 48 saatin haberleri alınır
- Her kategoriden 2 haber = 12 haber/çalışma
- Firebase'de max 48 haber
- Hatalı LLM çıktıları Regex ile filtrelenir (===OZET=== hatası giderildi)
"""

import os, json, time, base64, hashlib, datetime, re
import xml.etree.ElementTree as ET
import requests
from email.utils import parsedate_to_datetime

# ─── AYARLAR ────────────────────────────────────────────────────────────────
KATEGORI_BASI_HABER = 2
MAX_HABER           = 48
SAAT_FILTRESI       = 48      # Son kaç saatin haberleri alınsın
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

KATEGORI_RSS = {
    "Yapay Zeka": [
        "https://news.google.com/rss/search?q=yapay+zeka+AI&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=chatgpt+gemini+yapay+zeka&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Donanım": [
        "https://news.google.com/rss/search?q=iphone+samsung+telefon+donanim&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=bilgisayar+chip+gpu+cihaz&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Yazılım": [
        "https://news.google.com/rss/search?q=yazilim+uygulama+guncelleme&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=mobil+uygulama+platform&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Sosyal Medya": [
        "https://news.google.com/rss/search?q=instagram+tiktok+twitter+sosyal+medya&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=youtube+facebook+sosyal+ag&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Siber Güvenlik": [
        "https://news.google.com/rss/search?q=siber+guvenlik+hack+saldiri&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=veri+ihlali+fidye+yazilim&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "Teknoloji": [
        "https://news.google.com/rss/search?q=teknoloji+girisim+startup&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=blockchain+kripto+fintech&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
}
# ─────────────────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def turkce_mi(baslik):
    latin_ve_turkce = set('abcçdefgğhıijklmnoöpqrsştuüvwxyzABCÇDEFGĞHIİJKLMNOÖPQRSŞTUÜVWXYZ0123456789 .,!?:;\'"-()[]&@#%+/\\')
    toplam = len(baslik)
    if toplam == 0:
        return False
    latin_sayisi = sum(1 for c in baslik if c in latin_ve_turkce)
    return (latin_sayisi / toplam) >= 0.85

def baslik_temizle(baslik):
    temiz = re.sub(r'\s*[-|]\s*[^-|]{3,50}$', '', baslik).strip()
    return temiz if temiz else baslik

def haber_taze_mi(pub_date_str):
    if not pub_date_str:
        return True 
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        if pub_dt.tzinfo:
            import datetime as dt
            now_utc = dt.datetime.now(dt.timezone.utc)
            fark = now_utc - pub_dt
        else:
            fark = datetime.datetime.utcnow() - pub_dt.replace(tzinfo=None)
        return fark.total_seconds() < (SAAT_FILTRESI * 3600)
    except Exception:
        return True 

def rss_cek(url, kategori):
    try:
        r = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })
        r.encoding = "utf-8"
        root  = ET.fromstring(r.text)
        items = root.findall(".//item")
        haberler = []
        atlanan  = 0
        for item in items:
            baslik   = item.findtext("title",   "").strip()
            link     = item.findtext("link",    "").strip()
            pub_date = item.findtext("pubDate", "").strip()

            if not baslik or not link or len(baslik) < 10:
                continue

            if not turkce_mi(baslik):
                continue

            if not haber_taze_mi(pub_date):
                atlanan += 1
                continue

            haberler.append({
                "baslik":    baslik_temizle(baslik),
                "link":      link,
                "pub_date":  pub_date,
                "kategori":  kategori 
            })

        log(f"  RSS: {len(haberler)} taze haber ({atlanan} eski atlandı) ← {url[:50]}...")
        return haberler
    except Exception as e:
        log(f"  RSS HATA: {e}")
        return []

def groq_iste(sistem, kullanici, api_key, max_tokens=1500):
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
                eslesme = re.search(r'try again in (\d+\.?\d*)s', hata)
                bekle = float(eslesme.group(1)) + 1 if eslesme else RETRY_WAIT
                if deneme < RETRY_LIMIT - 1:
                    log(f"    Rate limit, {bekle:.0f}s bekleniyor...")
                    time.sleep(min(bekle, 30))
                    continue
                raise Exception(f"HTTP {r.status_code}: {hata[:100]}")

            metin = r.json()["choices"][0]["message"]["content"].strip()
            if "```" in metin:
                parcalar = metin.split("```")
                metin = parcalar[1] if len(parcalar) > 1 else parcalar[0]
                if metin.lower().startswith(("html", "json")):
                    metin = metin.split("\n", 1)[-1]
            return metin.strip()

        except Exception as e:
            if deneme < RETRY_LIMIT - 1:
                log(f"    Hata deneme {deneme+1}: {str(e)[:80]}, {RETRY_WAIT}s bekleniyor...")
                time.sleep(RETRY_WAIT)
            else:
                raise

def makale_uret(baslik, api_key):
    sistem = "Sen Hit Studios'un teknoloji editörüsün. Profesyonel, akıcı Türkçe teknoloji makaleleri yazıyorsun."
    kullanici = f"""Aşağıdaki haber başlığı hakkında Türkçe makale yaz.

Haber: {baslik}

Tam olarak şu formatta yaz, başka hiçbir şey ekleme:

===OZET===
Bu haberi özetleyen tek ve dikkat çekici bir Türkçe cümle buraya gelecek.
===ICERIK===
<p>Giriş paragrafı buraya gelecek. Haberin bağlamını anlat.</p>
<h3>Konuya uygun bir başlık</h3>
<p>İkinci paragraf buraya gelecek. Daha fazla detay ver.</p>
<p>Üçüncü paragraf buraya gelecek. Sonuç veya değerlendirme yap.</p>
===BITIS==="""

    metin = groq_iste(sistem, kullanici, api_key, 1200)

    # 1. YAPAY ZEKA SAPMALARINI DÜZELT (Yıldızları ve fazlalıkları sil, formatı sabitle)
    metin = re.sub(r'(?i)===\s*\*?\s*[oö]zet\s*\*?\s*===', '===OZET===', metin)
    metin = re.sub(r'(?i)===\s*\*?\s*[iı]çer[iı]k\s*\*?\s*===', '===ICERIK===', metin)
    metin = re.sub(r'(?i)===\s*\*?\s*b[iı]t[iı]ş\s*\*?\s*===', '===BITIS===', metin)
    
    # MD yıldızları varsa temizle
    metin = metin.replace('**===OZET===**', '===OZET===').replace('**===ICERIK===**', '===ICERIK===').replace('**===BITIS===**', '===BITIS===')

    ozet = ""
    icerik = ""
    
    # 2. BÖLÜMLEME (Regex ile çok daha güvenli arama)
    ozet_match = re.search(r'===OZET===(.*?)===ICERIK===', metin, re.DOTALL)
    icerik_match = re.search(r'===ICERIK===(.*?)(?:===BITIS===|\Z)', metin, re.DOTALL)

    if ozet_match and icerik_match:
        ozet = ozet_match.group(1).strip()
        icerik = icerik_match.group(1).strip()
    else:
        # 3. YEDEK PLAN: Ayraçlar hala bulunamazsa, içinde === geçen satırları silip temiz metni al
        temiz_satirlar = [s.strip() for s in metin.strip().split("\n") if not re.search(r'===.*?===', s)]
        temiz_satirlar = [s for s in temiz_satirlar if s] # Boş satırları at
        
        if len(temiz_satirlar) >= 2:
            ozet = temiz_satirlar[0]
            icerik = "\n".join(temiz_satirlar[1:])
        else:
            raise Exception("Format anlaşılamadı.")

    # 4. SON TEMİZLİK (Gözden kaçan == veya yıldızları sil)
    ozet = re.sub(r'===.*?===', '', ozet).strip()
    icerik = re.sub(r'===.*?===', '', icerik).strip()
    ozet = ozet.replace('**', '')

    if not ozet or not icerik:
        raise Exception("Özet veya içerik boş geldi")

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
    log("Hit Studios Haber Üretici v7.1 Başladı")
    log(f"Hedef: {len(KATEGORILER)} kategori × {KATEGORI_BASI_HABER} = {len(KATEGORILER)*KATEGORI_BASI_HABER} haber")
    log(f"Filtre: Son {SAAT_FILTRESI} saatin haberleri, sadece Türkçe/Latin")
    log("=" * 55)

    groq_key   = os.environ.get("GROQ_API_KEY", "")
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "hit-studios-web-2231e")
    fb_key_b64 = os.environ.get("FIREBASE_KEY", "")

    if not groq_key or not fb_key_b64:
        log("HATA: GROQ_API_KEY veya FIREBASE_KEY eksik!")
        return

    log("Groq bağlantısı test ediliyor...")
    try:
        test = groq_iste("Sen bir asistansın.", "Sadece 'OK' yaz.", groq_key, 10)
        log(f"Groq OK: {test[:20]}")
    except Exception as e:
        log(f"Groq HATA: {e}"); return

    try:
        token = get_access_token(base64.b64decode(fb_key_b64).decode("utf-8"))
        log("Firebase bağlantısı kuruldu.")
    except Exception as e:
        log(f"Firebase auth HATA: {e}"); return

    mevcut    = firebase_oku(project_id, token)
    var_idler = {h.get("id","") for h in mevcut}
    log(f"Mevcut haber sayısı: {len(mevcut)}")

    toplam_uretilen = 0

    for kategori in KATEGORILER:
        log(f"\n── {kategori} ──")
        kategori_sayac = 0

        # RSS'ten taze haberleri çek
        aday_haberler = []
        for url in KATEGORI_RSS.get(kategori, []):
            aday_haberler.extend(rss_cek(url, kategori))

        # Tekrarları kaldır
        gorulmus, benzersiz = set(), []
        for h in aday_haberler:
            k = h["baslik"][:60].lower()
            if k not in gorulmus:
                gorulmus.add(k)
                benzersiz.append(h)

        log(f"  Benzersiz taze haber: {len(benzersiz)}")

        if len(benzersiz) == 0:
            log(f"  ⚠ Son {SAAT_FILTRESI} saatte haber bulunamadı, atlanıyor.")
            continue

        for rss_h in benzersiz:
            if kategori_sayac >= KATEGORI_BASI_HABER:
                break

            hid = haber_id(rss_h["baslik"])
            if hid in var_idler:
                log(f"  Atlandı (zaten var): {rss_h['baslik'][:40]}...")
                continue

            log(f"  [{kategori_sayac+1}/{KATEGORI_BASI_HABER}] Üretiliyor: {rss_h['baslik'][:50]}...")

            try:
                ozet, icerik = makale_uret(rss_h["baslik"], groq_key)
            except Exception as e:
                log(f"  Hata (atlandı): {e}")
                continue

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
                log(f"  ✓ Yazıldı — Kategori: {kategori} (Toplam: {len(mevcut)})")
            except Exception as e:
                log(f"  Firebase HATA: {e}")

            kategori_sayac  += 1
            toplam_uretilen += 1
            time.sleep(3)

        log(f"  {kategori}: {kategori_sayac} haber üretildi.")

    log(f"\n{'='*55}")
    log(f"Tamamlandı! Üretilen: {toplam_uretilen} | Firebase: {len(mevcut)} haber")
    log("=" * 55)

if __name__ == "__main__":
    main()
