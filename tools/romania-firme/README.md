# Romanya CAEN 5621 firma listesi → Excel

Romanya'daki **CAEN 5621 – Activități de alimentație (catering) pentru evenimente**
firmalarını resmi açık veriden toplar. Firmalar il il ayrı sayfalara yazılır ve
**cirodan büyükten küçüğe** sıralanır.

## Nasıl çalışır

| Adım | Kaynak | Ne alınır |
|---|---|---|
| 1 | data.gov.ro – ONRC (Registrul Comerțului) | 5621 için yetkili bütün firmalar (aday liste), il, şehir, sicil no |
| 2 | ANAF TVA API | adres, telefon, kayıt durumu |
| 3 | ANAF bilanț API | **CAEN preponderent**, ciro, net kâr, çalışan sayısı (son 2 yıl) |

Son listede sadece bilançosundaki **ana faaliyeti 5621** olan firmalar kalır.
listafirme'deki "Cod CAEN preponderent" alanı da buradan gelir. Rev. 2 ve Rev. 3'te
kod aynıdır (5621), ikisi de kapsanır.

## Kurulum (bir kere)

1. Python 3.10+ kurun: https://www.python.org/downloads/ (Windows'ta **"Add python to PATH"** kutusunu işaretleyin).
2. Bu klasörde bir terminal açın ve şunu çalıştırın:
   ```
   pip install -r requirements.txt
   ```

## Çalıştırma

```
python firme_5621.py
```

- İlk çalıştırmada ONRC dosyaları (birkaç yüz MB) `onrc/` klasörüne indirilir.
- ANAF'a saniyede 1 istek gönderilir. Aday sayısına göre **birkaç saat** sürebilir,
  bilgisayarı açık bırakmanız yeterli.
- Elektrik kesilirse veya pencereyi kapatırsanız **aynı komutu tekrar çalıştırın**.
  Cevaplar `cache/` klasöründe saklanır, script kaldığı yerden devam eder.
- Sonuç: `firme_caen_5621_YYYYMMDD.xlsx`
  - `TOATE` sayfası tüm Romanya'yı içerir.
  - Her il (județ) için ayrı bir sayfa vardır.

### Seçenekler

| Seçenek | Açıklama |
|---|---|
| `--group localitate` | İl yerine şehir/kasaba bazında sayfa açar (yüzlerce sayfa olabilir) |
| `--years 2024,2023` | Hangi bilanço yılları denensin |
| `--onrc-dir KLASOR` | ONRC dosyalarını elle indirdiyseniz klasörünü gösterir |
| `--include-other-main-caen` | Ana faaliyeti 5621 olmayan ama 5621 yetkisi olanları da ekler |
| `--caen 5610` | Başka bir CAEN kodu için çalıştırır |

## Sorun çıkarsa

- **"An Application Control policy has blocked this file":** Bu Windows Smart App Control
  uyarısıdır. Script artık pandas gibi derlenmiş paket kullanmıyor, sadece `openpyxl`
  gerekiyor (saf Python).
- **"ONRC seti bulunamadı":** https://data.gov.ro/dataset?q=firme+inregistrate+registrul+comertului
  adresinden en güncel seti açın, `od_firme`, `od_caen_autorizat`, `od_stare_firma` ve
  `n_stare_firma` dosyalarını `onrc/` klasörüne indirip tekrar çalıştırın.
- **ANAF API adresi değiştiyse** (ör. `v9` → `v10`): dosyanın başındaki `ANAF_TVA`
  satırını güncelleyin.
