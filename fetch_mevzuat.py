"""
Hit Studios - Lokanta Mevzuat Üretici v1.0
- Resmi Gazete RSS + Google News'ten SADECE Resmi Gazete gıda/işletme mevzuatı çeker
- Groq ile özetler ve Firebase'e yazar
- Sol panel: Mevzuat/Kanun (Sadece Resmi Gazete), Sağ panel: Haberler/Duyurular (Sektörel Haberler)
- Firebase: hit_data/lokanta_mevzuat
"""

import os, json, time, base64, hashlib, datetime, re
import xml.etree.ElementTree as ET
import requests
from email.utils import parsedate_to_datetime

# ─── AYARLAR ────────────────────────────────────────────────────────────────
KATEGORI_BASI_HABER = 3
MAX_HABER           = 40
SAAT_FILTRESI       = 72    # 3 gün — resmi gazete her gün çıkmayabilir
GROQ_MODEL          = "llama-3.1-8b-instant"
RETRY_LIMIT         = 3
RETRY_WAIT          = 8

KATEGORILER = {
    "mevzuat": [   # Sol panel - SADECE RESMİ GAZETE
        "https://www.resmigazete.gov.tr/rss",
        "https://news.google.com/rss/search?q=site:resmigazete.gov.tr+(gida+OR+restoran+OR+lokanta+OR+vergi+OR+yonetmelik+OR+teblig)&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
    "duyuru": [    # Sağ panel - SADECE SEKTÖREL HABERLER (Lokanta/Kafe/Gıda)
        "https://news.google.com/rss/search?q=gida+denetim+tarim+bakanligi+turkiye+2026&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=lokanta+restoran+kafe+vergi+sgk+ceza+turkiye&hl=tr&gl=TR&ceid=TR%3Atr",
        "https://news.google.com/rss/search?q=gida+guvenligi+haber+saglik+bakanligi+turkiye&hl=tr&gl=TR&ceid=TR%3Atr",
    ],
}
# ─────────────────────────────────────────────────────────────────────────────

ENGELLI_DOMAIN = [
    'vietnam.vn', '.vn/', 'aljazeera', 'bbc.', 'reuters.', 'bloomberg.',
    'theguardian', 'nytimes', 'washingtonpost', 'france24', 'dw.com',
]

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def turkce_kaynak_mi(link):
    """Yabancı kaynak domainlerini filtrele."""
    link_lower = link.lower()
    for domain in ENGELLI_DOMAIN:
        if domain in link_lower:
            return False
    return True

def turkce_mi(baslik):
    latin_ve_turkce = set('abcçdefgğhıijklmnoöpqrsştuüvwxyzABCÇDEFGĞHIİJKLMNOÖPQRSŞTUÜVWXYZ0123456789 .,!?:;\'"-()/\\')
    toplam = len(baslik)
    if toplam == 0: return False
    latin_sayisi = sum(1 for c in baslik if c in latin_ve_turkce)
    return (latin_sayisi / toplam) >= 0.80

def baslik_temizle(baslik):
    temiz = re.sub(r'\s*[-|]\s*[^-|]{3,50}$', '', baslik).strip()
    return temiz if temiz else baslik

def haber_taze_mi(pub_date_str):
    if not pub_date_str: return True
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        if pub_dt.tzinfo:
            import datetime as dt
            fark = dt.datetime.now(dt.timezone.utc) - pub_dt
        else:
            fark = datetime.datetime.utcnow() - pub_dt.replace(tzinfo=None)
        return fark.total_seconds() < (SAAT_FILTRESI * 3600)
    except:
        return True

def rss_cek(url, panel):
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
            if not baslik or not link or len(baslik) < 8: continue
            if not turkce_kaynak_mi(link): continue
            if not turkce_mi(baslik): continue
            if not haber_taze_mi(pub_date): atlanan += 1; continue
            haberler.append({
                "baslik":   baslik_temizle(baslik),
                "link":     link,
                "pub_date": pub_date,
                "panel":    panel
            })
        log(f"  RSS: {len(haberler)} taze ({atlanan} eski) ← {url[:55]}...")
        return haberler
    except Exception as e:
        log(f"  RSS HATA: {e}")
        return []

def groq_iste(sistem, kullanici, api_key, max_tokens=1000):
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
                    "temperature": 0.5
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
                raise Exception(f"HTTP {r.status_code}")
            metin = r.json()["choices"][0]["message"]["content"].strip()
            if "```" in metin:
                parcalar = metin.split("```")
                metin = parcalar[1] if len(parcalar) > 1 else parcalar[0]
                if metin.lower().startswith(("html","json")): metin = metin.split("\n",1)[-1]
            return metin.strip()
        except Exception as e:
            if deneme < RETRY_LIMIT - 1:
                log(f"    Hata {deneme+1}: {str(e)[:60]}, {RETRY_WAIT}s...")
                time.sleep(RETRY_WAIT)
            else:
                raise

def ilgili_mi(baslik, api_key):
    """Haber gıda/restoran/işletme ile ilgili mi kontrol et."""
    sistem = "Sen bir asistansın. Sadece EVET veya HAYIR yaz."
    kullanici = f"""Bu haber başlığı; restoran, kafe, lokanta, gıda işletmesi, yiyecek-içecek sektörü, 
gıda güvenliği, işletme vergi/sgk/mevzuat konularından biriyle ilgili mi?

Başlık: {baslik}

Sadece EVET veya HAYIR yaz:"""
    try:
        cevap = groq_iste(sistem, kullanici, api_key, 5)
        return "EVET" in cevap.upper()
    except:
        return True  # Hata varsa kabul et

def ozet_uret(baslik, panel, api_key):
    if panel == "mevzuat":
        sistem = "Sen gıda ve işletme mevzuatı konusunda uzman bir hukuk editörüsün. Kısa, net Türkçe özetler yazıyorsun."
        tur = "mevzuat/kanun/yönetmelik"
    else:
        sistem = "Sen gıda sektörü haberlerini takip eden bir editörüsün. Kısa, net Türkçe özetler yazıyorsun."
        tur = "haber/duyuru"

    kullanici = f"""Bu {tur} başlığı için şu formatta yaz:

Başlık: {baslik}

===OZET===
İşletmeciler için ne anlama geldiğini açıklayan tek cümle.
===ETIKET===
Tek kelime etiket (örn: Vergi, SGK, Gıda, Denetim, Ruhsat, Hijyen, İstihdam, Mevzuat)
===BITIS==="""

    metin = groq_iste(sistem, kullanici, api_key, 200)

    # Parse
    metin = re.sub(r'(?i)===\s*ozet\s*===', '===OZET===', metin)
    metin = re.sub(r'(?i)===\s*etiket\s*===', '===ETIKET===', metin)
    metin = re.sub(r'(?i)===\s*bitis\s*===', '===BITIS===', metin)

    ozet_m   = re.search(r'===OZET===(.*?)===ETIKET===', metin, re.DOTALL)
    etiket_m = re.search(r'===ETIKET===(.*?)(?:===BITIS===|\Z)', metin, re.DOTALL)

    ozet   = ozet_m.group(1).strip()   if ozet_m   else baslik[:100]
    etiket = etiket_m.group(1).strip() if etiket_m else ("Mevzuat" if panel == "mevzuat" else "Duyuru")
    etiket = etiket.split('\n')[0].strip()[:20]

    return ozet, etiket

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
    jwt = (signing_input + b"." + sig).decode()
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt
    })
    if not r.ok: raise Exception(f"Token hatası: {r.text}")
    return r.json()["access_token"]

def firebase_oku(project_id, token):
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/hit_data/lokanta_mevzuat"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if not r.ok: return []
        data = r.json()
        vals = data.get("fields",{}).get("items",{}).get("arrayValue",{}).get("values",[])
        return [{k: list(v.values())[0] for k,v in item.get("mapValue",{}).get("fields",{}).items()} for item in vals]
    except Exception as e:
        log(f"Firebase okuma: {e}"); return []

def firebase_yaz(project_id, token, items):
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/hit_data/lokanta_mevzuat"
    def to_fs(h):
        return {"mapValue": {"fields": {k: {"stringValue": str(v).replace("\x00","").replace("\r","")} for k,v in h.items()}}}
    body = {"fields": {"items": {"arrayValue": {"values": [to_fs(h) for h in items]}}}}
    r = requests.patch(url, data=json.dumps(body, ensure_ascii=True).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=30)
    if not r.ok: raise Exception(f"Firebase yazma: {r.status_code} {r.text[:150]}")

def haber_id(baslik):
    return hashlib.md5(baslik.encode("utf-8")).hexdigest()[:12]

def tarih_tr():
    aylar = ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran","Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"]
    d = datetime.datetime.now()
    return f"{d.day} {aylar[d.month-1]} {d.year}"

def main():
    log("=" * 55)
    log("Lokanta Mevzuat Üretici v1.0 Başladı")
    log(f"Filtre: Son {SAAT_FILTRESI} saat | Panel başına {KATEGORI_BASI_HABER} içerik")
    log("=" * 55)

    groq_key   = os.environ.get("GROQ_API_KEY", "")
    project_id = os.environ.get("FIREBASE_PROJECT_ID", "hit-studios-web-2231e")
    fb_key_b64 = os.environ.get("FIREBASE_KEY", "")

    if not groq_key or not fb_key_b64:
        log("HATA: GROQ_API_KEY veya FIREBASE_KEY eksik!"); return

    log("Groq test...")
    try:
        test = groq_iste("Sen bir asistansın.", "Sadece OK yaz.", groq_key, 5)
        log(f"Groq OK: {test[:10]}")
    except Exception as e:
        log(f"Groq HATA: {e}"); return

    try:
        token = get_access_token(base64.b64decode(fb_key_b64).decode("utf-8"))
        log("Firebase bağlantısı kuruldu.")
    except Exception as e:
        log(f"Firebase HATA: {e}"); return

    mevcut    = firebase_oku(project_id, token)
    var_idler = {h.get("id","") for h in mevcut}
    log(f"Mevcut içerik: {len(mevcut)}")

    toplam = 0

    for panel, urls in KATEGORILER.items():
        log(f"\n── Panel: {panel} ──")
        sayac = 0
        adaylar = []
        for url in urls:
            adaylar.extend(rss_cek(url, panel))

        # Tekrar kaldır
        gorulmus, benzersiz = set(), []
        for h in adaylar:
            k = h["baslik"][:60].lower()
            if k not in gorulmus:
                gorulmus.add(k)
                benzersiz.append(h)

        log(f"  Benzersiz taze: {len(benzersiz)}")

        for h in benzersiz:
            if sayac >= KATEGORI_BASI_HABER: break
            hid = haber_id(h["baslik"])
            if hid in var_idler:
                log(f"  Atlandı (var): {h['baslik'][:40]}...")
                continue

            log(f"  Kontrol: {h['baslik'][:50]}...")
            try:
                if not ilgili_mi(h["baslik"], groq_key):
                    log(f"  → İlgisiz, atlandı.")
                    continue
                time.sleep(1)
                ozet, etiket = ozet_uret(h["baslik"], panel, groq_key)
            except Exception as e:
                log(f"  Hata: {e}"); continue

            yeni = {
                "id":     hid,
                "baslik": h["baslik"],
                "ozet":   ozet,
                "etiket": etiket,
                "panel":  panel,
                "tarih":  tarih_tr(),
                "kaynak": h["link"]
            }
            mevcut.insert(0, yeni)
            mevcut = mevcut[:MAX_HABER]
            var_idler.add(hid)

            try:
                firebase_yaz(project_id, token, mevcut)
                log(f"  ✓ Yazıldı [{panel}] {etiket}: {h['baslik'][:40]}")
            except Exception as e:
                log(f"  Firebase HATA: {e}")

            sayac  += 1
            toplam += 1
            time.sleep(3)

        log(f"  {panel}: {sayac} içerik üretildi.")

    log(f"\n{'='*55}")
    log(f"Tamamlandı! Üretilen: {toplam} | Firebase: {len(mevcut)}")
    log("=" * 55)

if __name__ == "__main__":
    main()
