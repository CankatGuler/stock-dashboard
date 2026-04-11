# director_memory.py — Direktör Hafıza Sistemi
#
# Bu modül, strateji direktörüne "balık hafızasından" kurtulma yeteneği kazandırır.
# Dört boyutlu bir Durum Makinesi (State Machine) olarak tasarlanmıştır:
#
#   1. Karar Günlüğü      — Ne zaman, hangi rejimde, ne kararı verdik?
#   2. Whipsaw Kilidi      — Çift koşullu (zaman + makro) sürtünme mekanizması
#   3. Pozisyon Hafızası   — Kümülatif pozisyon takibi, Zeno paradoksunu önler
#   4. Karar Performansı   — Direktörün geçmiş kararlarını kalibrasyon için kullanır
#
# Dışarıya sunduğu üç şey:
#   memory.save_decision(...)    → Yeni kararı kaydet
#   memory.check_whipsaw(...)    → Bu varlık kilitli mi?
#   memory.build_context(...)    → Direktöre enjekte edilecek sentezlenmiş bağlam

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Hafıza dosyasının yolu — GitHub repo'da saklanır, böylece Actions runs arası kalıcıdır
MEMORY_FILE = Path(__file__).parent / "director_memory.json"

# Kaç günlük karar geçmişi direktöre gösterilecek (token optimizasyonu)
CONTEXT_WINDOW_DAYS = 30

# Performans takibi için varlıkların fiyatı kaç gün sonra kontrol edilecek
PERFORMANCE_CHECK_DAYS = 14


# ─── Yardımcı: Dosya Okuma/Yazma ─────────────────────────────────────────────

def _load() -> dict:
    """
    Hafıza dosyasını diskten oku.
    Dosya yoksa veya bozuksa temiz bir yapı döndür.
    """
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Hafıza dosyası okunamadı, sıfırlanıyor: %s", e)
    return {"decisions": [], "performance": [], "whipsaw_locks": {}}


def _save(data: dict) -> None:
    """Hafıza dosyasını diske yaz."""
    try:
        MEMORY_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error("Hafıza yazma hatası: %s", e)


# ─── Ana Sınıf: MemoryManager ─────────────────────────────────────────────────

class MemoryManager:
    """
    Direktörün hafıza yöneticisi.

    Temel kullanım:
        memory = MemoryManager()
        memory.save_decision(...)        # Analiz sonrası kaydeder
        context = memory.build_context() # Analiz öncesi enjekte eder
        locked  = memory.check_whipsaw("TTE")  # Kilitli mi?
    """

    def __init__(self):
        self._data = _load()

    # ── 1. Karar Kaydetme ─────────────────────────────────────────────────────

    def save_decision(
        self,
        vix:            float,
        btc_fiyat:      float,
        usdtry:         float,
        rejim:          str,
        ana_aksiyonlar: list[dict],   # [{"varlik":"TTE","eylem":"SAT","miktar_pct":50,"fiyat":9.5}, ...]
        ozet:           str,
        trigger_kaynagi: str = "manuel",  # "katman_1", "katman_2", "sabah_ozeti", "manuel"
    ) -> None:
        """
        Yeni bir direktör kararını hafızaya kaydet.

        Aynı zamanda:
          - Rejim sürekliliği sayacını günceller
          - Whipsaw kilitlerini işler
          - Performans takibi için fiyatları kaydeder
        """
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Rejim sürekliliği: aynı rejim kaç gündür devam ediyor?
        sureklilik = self._hesapla_sureklilik(rejim)

        # Karar kaydını oluştur
        karar = {
            "tarih":            today_str,
            "vix":              round(vix, 1),
            "btc_fiyat":        round(btc_fiyat, 0),
            "usdtry":           round(usdtry, 2),
            "rejim":            rejim,
            "rejim_surekliligi_gun": sureklilik,
            "ana_aksiyonlar":   ana_aksiyonlar,
            "trigger_kaynagi":  trigger_kaynagi,
            "ozet":             ozet[:300],  # token tasarrufu için sınırla
        }
        self._data["decisions"].append(karar)

        # Sadece son 90 kararı sakla (daha eskisi performans takibinde kullanılabilir)
        self._data["decisions"] = self._data["decisions"][-90:]

        # Whipsaw kilitlerini güncelle
        self._guncelle_whipsaw_kilitleri(ana_aksiyonlar, today_str, vix)

        # Performans takibi için varlık fiyatlarını kaydet
        self._kaydet_performans_baseline(ana_aksiyonlar, today_str)

        _save(self._data)
        logger.info("Karar kaydedildi: %s | %s | %d aksiyon",
                    today_str, rejim, len(ana_aksiyonlar))

    def _hesapla_sureklilik(self, yeni_rejim: str) -> int:
        """
        Aynı rejim kaç gündür devam ediyor?
        Direktöre "yorgunluk" bağlamı verir.
        """
        if not self._data["decisions"]:
            return 1

        # Geriye doğru tara — aynı rejim kaç ardışık kayıtta var?
        gun_sayisi = 1
        for karar in reversed(self._data["decisions"]):
            if karar.get("rejim") == yeni_rejim:
                # Tarih farkını hesapla
                try:
                    gecen_gun = (
                        datetime.now(timezone.utc).date() -
                        datetime.fromisoformat(karar["tarih"]).date()
                    ).days
                    gun_sayisi = max(gun_sayisi, gecen_gun + 1)
                except Exception:
                    gun_sayisi += 1
            else:
                break
        return gun_sayisi

    # ── 2. Whipsaw Kilit Sistemi ──────────────────────────────────────────────

    def _guncelle_whipsaw_kilitleri(
        self,
        aksiyonlar: list[dict],
        tarih_str:  str,
        vix:        float,
    ) -> None:
        """
        SAT veya AZALT aksiyonları için whipsaw kilidi oluştur.
        Kilit koşulu: zaman (5 iş günü) VE makro eşik (VIX - 5 puan).

        Mantık: Bir varlığı sattıysan, VIX hem 5 gün sonra hem de
        bugünkü değerden en az 5 puan aşağıda olmadan geri almamalısın.
        Bu çift güvence, panikle satıp panikle geri almayı önler.
        """
        locks = self._data.setdefault("whipsaw_locks", {})

        for a in aksiyonlar:
            eylem  = a.get("eylem", "")
            varlik = a.get("varlik", "")
            if eylem in ("SAT", "AZALT") and varlik:
                locks[varlik] = {
                    "kilitli_tarih":   tarih_str,
                    "kilit_vix":       round(vix, 1),
                    # Kilit açılış koşulları — her ikisi de sağlanmalı
                    "min_is_gunu":     5,
                    "vix_esigi":       round(vix - 5, 1),  # Satış anındaki VIX - 5
                    "aciklama":        (
                        f"{tarih_str} tarihinde {eylem} edildi "
                        f"(VIX={vix:.1f}). Geri almak için: "
                        f"5 iş günü geçmeli VE VIX < {vix - 5:.1f} olmalı."
                    ),
                }
                logger.info("Whipsaw kilidi oluşturuldu: %s (VIX eşiği: %.1f)",
                            varlik, vix - 5)

    def check_whipsaw(self, varlik: str, mevcut_vix: float) -> dict:
        """
        Bir varlık whipsaw kilidi altında mı?

        Döndürür:
            {"kilitli": True/False, "sebep": "açıklama", "gun_kaldi": N}

        Direktör bu bilgiyi prompt'a ekleyerek "neden beklemeli" sorusunu yanıtlar.
        """
        locks = self._data.get("whipsaw_locks", {})
        if varlik not in locks:
            return {"kilitli": False, "sebep": "", "gun_kaldi": 0}

        lock = locks[varlik]

        # Zaman kontrolü
        try:
            kilitli_tarih = datetime.fromisoformat(lock["kilitli_tarih"]).date()
            gecen_gun = (datetime.now(timezone.utc).date() - kilitli_tarih).days
            # İş günü hesabı (hafta sonları sayılmaz)
            gecen_is_gunu = sum(
                1 for i in range(gecen_gun)
                if (kilitli_tarih + timedelta(days=i+1)).weekday() < 5
            )
        except Exception:
            gecen_is_gunu = 0

        zaman_ok  = gecen_is_gunu >= lock.get("min_is_gunu", 5)
        makro_ok  = mevcut_vix < lock.get("vix_esigi", 999)
        gun_kaldi = max(0, lock.get("min_is_gunu", 5) - gecen_is_gunu)

        if zaman_ok and makro_ok:
            # Her iki koşul da sağlandı — kilidi kaldır
            del locks[varlik]
            _save(self._data)
            logger.info("Whipsaw kilidi kaldırıldı: %s", varlik)
            return {"kilitli": False, "sebep": "Kilit koşulları sağlandı", "gun_kaldi": 0}

        sebep_parcalar = []
        if not zaman_ok:
            sebep_parcalar.append(f"{gun_kaldi} iş günü daha beklenmeli")
        if not makro_ok:
            sebep_parcalar.append(
                f"VIX {mevcut_vix:.1f} > eşik {lock['vix_esigi']:.1f} — "
                f"makro henüz yeterince iyileşmedi"
            )

        return {
            "kilitli":   True,
            "sebep":     " | ".join(sebep_parcalar),
            "gun_kaldi": gun_kaldi,
            "kilit_vix": lock.get("kilit_vix", 0),
        }

    # ── 3. Pozisyon Büyüklüğü Hafızası ────────────────────────────────────────

    def get_cumulative_position_context(self, varlik: str) -> str:
        """
        Bir varlık için kümülatif işlem geçmişini özetle.

        Zeno Paradoksunu önler: Direktör "IIH'yi %50 azalt" demeye devam ederse
        portföyde IIH hiç sıfırlanamaz. Bu fonksiyon direktöre
        "toplam ne kadar sattığını" hatırlatır.

        Döndürür: Direktöre enjekte edilecek kısa metin.
        """
        toplam_sat_pct  = 0.0
        toplam_al_pct   = 0.0
        islem_sayisi    = 0
        son_islem_tarihi = ""

        for karar in self._data.get("decisions", []):
            for a in karar.get("ana_aksiyonlar", []):
                if a.get("varlik", "").upper() == varlik.upper():
                    islem_sayisi += 1
                    son_islem_tarihi = karar["tarih"]
                    eylem   = a.get("eylem", "")
                    miktar  = float(a.get("miktar_pct", 0) or 0)
                    if eylem in ("SAT", "AZALT"):
                        toplam_sat_pct += miktar
                    elif eylem in ("AL", "ARTIR"):
                        toplam_al_pct  += miktar

        if islem_sayisi == 0:
            return ""

        net_pct = toplam_sat_pct - toplam_al_pct
        yon     = "satıldı (azaltıldı)" if net_pct > 0 else "alındı (artırıldı)"

        return (
            f"{varlik}: Son {CONTEXT_WINDOW_DAYS} günde {islem_sayisi} işlem. "
            f"Net %{abs(net_pct):.0f} {yon}. "
            f"Son işlem: {son_islem_tarihi}. "
            f"Bugün tekrar {'SAT/AZALT' if net_pct < 0 else 'AL/ARTIR'} diyorsan "
            f"kümülatif pozisyona dikkat et."
        )

    # ── 4. Karar Performans Takibi ─────────────────────────────────────────────

    def _kaydet_performans_baseline(
        self,
        aksiyonlar: list[dict],
        tarih_str:  str,
    ) -> None:
        """
        SAT/AL aksiyonları için başlangıç fiyatını kaydet.
        PERFORMANCE_CHECK_DAYS sonra fiyat tekrar kontrol edilecek.
        """
        perf_kayitlar = self._data.setdefault("performance", [])

        for a in aksiyonlar:
            eylem  = a.get("eylem", "")
            varlik = a.get("varlik", "")
            fiyat  = a.get("fiyat", 0)

            if eylem in ("SAT", "AZALT", "AL", "ARTIR") and varlik and fiyat:
                perf_kayitlar.append({
                    "tarih":          tarih_str,
                    "varlik":         varlik,
                    "eylem":          eylem,
                    "baslangic_fiyat": float(fiyat),
                    "kontrol_tarihi": (
                        datetime.now(timezone.utc) +
                        timedelta(days=PERFORMANCE_CHECK_DAYS)
                    ).strftime("%Y-%m-%d"),
                    "kontrol_fiyat":  None,   # Sonra doldurulacak
                    "getiri_pct":     None,
                    "karar_isabeti":  None,   # "DOGRU" | "YANLIS" | "NÖTR"
                })

        # Sadece son 200 performans kaydını sakla
        self._data["performance"] = perf_kayitlar[-200:]

    def update_performance(self, varlik: str, guncel_fiyat: float) -> list[dict]:
        """
        Kontrol tarihi geçmiş performans kayıtlarını güncelle.
        GitHub Actions'ta haftada bir çalışacak.

        Döndürür: Güncellenen kayıtların listesi.
        """
        guncellenenler = []
        today = datetime.now(timezone.utc).date()

        for kayit in self._data.get("performance", []):
            if kayit.get("varlik") != varlik:
                continue
            if kayit.get("kontrol_fiyat") is not None:
                continue  # Zaten güncellenmiş

            try:
                kontrol_tarihi = datetime.fromisoformat(
                    kayit["kontrol_tarihi"]
                ).date()
            except Exception:
                continue

            if today >= kontrol_tarihi:
                bas_fiyat = float(kayit["baslangic_fiyat"])
                getiri    = (guncel_fiyat - bas_fiyat) / bas_fiyat * 100

                # Karar isabeti: Sat dedik, fiyat düştü mü?
                eylem = kayit["eylem"]
                if eylem in ("SAT", "AZALT"):
                    isabetli = getiri < -2   # Sattık, fiyat düştü → Doğru
                    yanlis   = getiri > 5    # Sattık, fiyat yükseldi → Yanlış
                else:  # AL / ARTIR
                    isabetli = getiri > 2    # Aldık, fiyat yükseldi → Doğru
                    yanlis   = getiri < -5   # Aldık, fiyat düştü → Yanlış

                kayit["kontrol_fiyat"] = round(guncel_fiyat, 4)
                kayit["getiri_pct"]    = round(getiri, 2)
                kayit["karar_isabeti"] = (
                    "DOGRU" if isabetli else
                    "YANLIS" if yanlis  else
                    "NÖTR"
                )
                guncellenenler.append(kayit)
                logger.info(
                    "Performans güncellendi: %s %s → %s (%+.1f%% | %s)",
                    kayit["tarih"], varlik, eylem, getiri, kayit["karar_isabeti"]
                )

        if guncellenenler:
            _save(self._data)

        return guncellenenler

    # ── Ana Fonksiyon: Direktöre Bağlam Üret ──────────────────────────────────

    def build_context(
        self,
        mevcut_vix: float   = 0,
        mevcut_btc: float   = 0,
        mevcut_try: float   = 0,
    ) -> str:
        """
        Direktöre enjekte edilecek sentezlenmiş hafıza bağlamını üret.

        Token optimizasyonu için tüm JSON yerine sadece işlenmiş özet enjekte edilir.
        Maksimum ~400-500 token hedeflenmiştir.

        İçerik:
          - Son karar özeti (rejim, aksiyonlar, süreklilik)
          - Aktif whipsaw kilitleri (direktörü uyarır)
          - Performans kalibrasyonu (doğru/yanlış kararlar)
          - Pozisyon kümülatif uyarıları
        """
        decisions = self._data.get("decisions", [])
        if not decisions:
            return ""  # Hiç hafıza yoksa boş dön — ilk çalışma

        lines = ["═" * 50,
                 "DİREKTÖR HAFIZA KAYDI — SON KARARLAR",
                 "═" * 50]

        # ── Son Karar Özeti ────────────────────────────────────────────────────
        son_karar = decisions[-1]
        lines.append(
            f"\n📅 SON KARAR: {son_karar['tarih']} | "
            f"Rejim: {son_karar['rejim']} | "
            f"VIX={son_karar['vix']} | "
            f"BTC=${son_karar['btc_fiyat']:,.0f} | "
            f"USD/TRY={son_karar['usdtry']}"
        )
        lines.append(f"Özet: {son_karar['ozet']}")

        # Aksiyonları özetle
        if son_karar.get("ana_aksiyonlar"):
            aksiyon_str = " | ".join(
                f"{a['eylem']} {a['varlik']}"
                + (f" %{a.get('miktar_pct','?')}" if a.get('miktar_pct') else "")
                for a in son_karar["ana_aksiyonlar"][:5]
            )
            lines.append(f"Aksiyonlar: {aksiyon_str}")

        # ── Rejim Sürekliliği Yorumu ───────────────────────────────────────────
        sureklilik = son_karar.get("rejim_surekliligi_gun", 1)
        rejim      = son_karar["rejim"]
        if sureklilik >= 21:
            lines.append(
                f"\n⚠️ REJİM YORGUNLUĞU: '{rejim}' rejimi {sureklilik} gündür devam ediyor. "
                f"Bu kadar uzun süren bir rejim mean-reversion baskısı biriktirir. "
                f"Seller/Buyer exhaustion ihtimali arttı — ani ters hareket için hazır ol."
            )
        elif sureklilik >= 10:
            lines.append(
                f"\n💡 Rejim Notu: '{rejim}' {sureklilik} gündür aktif. "
                f"Süreklilik orta seviyede — trend devam edebilir ama gözlemle."
            )

        # ── Piyasa Değişim Karşılaştırması ────────────────────────────────────
        if mevcut_vix > 0 and son_karar.get("vix", 0) > 0:
            vix_fark  = mevcut_vix - son_karar["vix"]
            btc_fark  = ((mevcut_btc - son_karar["btc_fiyat"]) /
                         son_karar["btc_fiyat"] * 100
                         if son_karar.get("btc_fiyat") else 0)
            try_fark  = mevcut_try - son_karar.get("usdtry", mevcut_try)

            lines.append(
                f"\n📊 SON KARARDAN BU YANA DEĞİŞİM ({son_karar['tarih']} → bugün):"
            )
            lines.append(
                f"  VIX: {son_karar['vix']} → {mevcut_vix:.1f} ({vix_fark:+.1f})"
            )
            lines.append(
                f"  BTC: ${son_karar['btc_fiyat']:,.0f} → ${mevcut_btc:,.0f} "
                f"({btc_fark:+.1f}%)"
            )
            lines.append(
                f"  USD/TRY: {son_karar['usdtry']} → {mevcut_try:.2f} "
                f"({try_fark:+.2f})"
            )
            lines.append(
                "  GÖREV: Analizine 'Son karardan bu yana makro tablo nasıl değişti?' "
                "sorusunu bir cümleyle yanıtlayarak başla."
            )

        # ── Aktif Whipsaw Kilitleri ────────────────────────────────────────────
        locks = self._data.get("whipsaw_locks", {})
        aktif_kilitler = []
        for varlik, lock in locks.items():
            kontrol = self.check_whipsaw(varlik, mevcut_vix)
            if kontrol["kilitli"]:
                aktif_kilitler.append(
                    f"  🔒 {varlik}: {kontrol['sebep']}"
                )

        if aktif_kilitler:
            lines.append("\n🔒 WHİPSAW KİLİTLERİ (bu varlıkları geri almak için koşullar sağlanmamış):")
            lines.extend(aktif_kilitler)
            lines.append(
                "  KURAL: Kilitli varlıklar için AL/ARTIR önerisi yapacaksan, "
                "kilit koşullarının neden artık geçersiz olduğunu açıkla."
            )

        # ── Performans Kalibrasyonu ────────────────────────────────────────────
        kalibrasyon = self._hesapla_kalibrasyon()
        if kalibrasyon:
            lines.append(f"\n📈 KARAR KALİBRASYONU (son {CONTEXT_WINDOW_DAYS} gün):")
            lines.append(f"  {kalibrasyon}")

        lines.append("═" * 50)

        context = "\n".join(lines)
        logger.info("Hafıza bağlamı üretildi: %d karakter", len(context))
        return context

    def _hesapla_kalibrasyon(self) -> str:
        """
        Geçmiş kararların isabetini özetle.
        Direktöre hangi konularda hata yaptığını söyler.
        """
        perf = self._data.get("performance", [])
        if not perf:
            return ""

        # Sadece değerlendirilmiş kayıtlar
        degerlendirilmis = [p for p in perf if p.get("karar_isabeti")]
        if len(degerlendirilmis) < 3:
            return ""  # Yeterli veri yoksa kalibrasyon yapma

        dogru  = sum(1 for p in degerlendirilmis if p["karar_isabeti"] == "DOGRU")
        yanlis = sum(1 for p in degerlendirilmis if p["karar_isabeti"] == "YANLIS")
        notrt  = sum(1 for p in degerlendirilmis if p["karar_isabeti"] == "NÖTR")
        toplam = len(degerlendirilmis)

        basari_pct = dogru / toplam * 100

        # Hangi varlıklarda hata çok yapıldı?
        varlik_hatalar: dict[str, int] = {}
        for p in degerlendirilmis:
            if p["karar_isabeti"] == "YANLIS":
                v = p["varlik"]
                varlik_hatalar[v] = varlik_hatalar.get(v, 0) + 1

        hata_str = ""
        if varlik_hatalar:
            en_cok_hata = max(varlik_hatalar, key=varlik_hatalar.get)
            hata_str = (
                f" {en_cok_hata} için {varlik_hatalar[en_cok_hata]} kez hatalı "
                f"zamanlama yapıldı — bu varlıkta daha geniş eşik kullan."
            )

        return (
            f"{toplam} kararın {dogru} doğru (%{basari_pct:.0f}), "
            f"{yanlis} yanlış, {notrt} nötr.{hata_str}"
        )

    # ── Yardımcı: Son N Karar ──────────────────────────────────────────────────

    def get_recent_decisions(self, n: int = 5) -> list[dict]:
        """Son N kararı döndür (en yeni en sonda)."""
        return self._data.get("decisions", [])[-n:]

    def get_current_regime(self) -> tuple[str, int]:
        """Mevcut rejim ve sürekliliği döndür."""
        decisions = self._data.get("decisions", [])
        if not decisions:
            return "Bilinmiyor", 0
        son = decisions[-1]
        return son.get("rejim", "Bilinmiyor"), son.get("rejim_surekliligi_gun", 1)

    def get_active_locks(self) -> dict:
        """Tüm aktif whipsaw kilitlerini döndür."""
        return dict(self._data.get("whipsaw_locks", {}))


# ─── Modül Seviyesi Tek Örnek ─────────────────────────────────────────────────
# Tüm dosyalar `from director_memory import memory` ile kullanır.
memory = MemoryManager()
