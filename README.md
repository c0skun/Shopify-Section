# Renk kartları (model) — Shopify tema bloğu

Ürün sayfasında, **aynı modelin farklı renklerini** temanın "Related products"
görünümüyle (aynı ürün kartı: görsel, rozet, fiyat, swatch, yıldızlar) gösterir.
Ürünler metafield/metaobject veya etiket ile **gruplanır**.

## Dosyalar

| Dosya | Tema içindeki yeri |
| --- | --- |
| `blocks/model-color-products.liquid` | `blocks/` |
| `snippets/model-color-products-item.liquid` | `snippets/` |

Tema düzenleyicide **Kodu düzenle** → ilgili klasörde aynı isimle yeni dosya
oluşturup içerikleri yapıştırın (veya Shopify CLI ile `shopify theme push`).

## Sayfaya ekleme

1. **Özelleştir** → Ürün şablonu → *Product details* grubunun içinde **Blok ekle**.
2. **Renk kartları (model)** bloğunu seçin, istediğiniz yere sürükleyin
   (ör. accordion'ların altı — ekran görüntüsündeki "Related products" konumu).
3. Masaüstü kolon: 2, görsel oranı: *Görsele uyarla*, puanı göster: açık →
   ekran görüntüsündeki görünüm.

Blok `@theme` kabul eden her section'a eklenebilir (tam genişlik bir alan için
ör. *Section* / *Custom section* içine de koyabilirsiniz).

## Ürünleri gruplama (birini seçin)

Blok aşağıdaki kaynakları sırayla dener, ilk dolu olanı kullanır.

### 1. Metaobject (önerilen — mevcut "Model renkleri" bloğuyla aynı veri)

1. **Ayarlar → Özel veriler → Metaobject'ler → Tanım ekle**: `Model Group`
   - Alan: `name` (tek satır metin)
   - Alan: `products` (**Ürün → Liste**)
2. **Ayarlar → Özel veriler → Ürünler → Tanım ekle**:
   `custom.model_group` → tip **Metaobject** (Model Group).
3. İçerik → Metaobject'ler → *Model Group* → örn. "Borderline One Piece"
   kaydı oluşturup tüm renk ürünlerini `products` alanına ekleyin.
4. Her renk ürününde `custom.model_group` alanına bu kaydı seçin.

Liste sırası = kart sırası.

### 2. Ürün listesi metafield'ı

`custom.color_siblings` (Ürün → Liste). Her üründe aynı modelin tüm
renklerini seçin.

### 3. Handle listesi

`custom.model_variants` (tek satır metin): `borderline-bay-blues,borderline-black`
(Shopify sayfa başına `all_products` ile en fazla 20 handle okur.)

### 4. Etiket + otomatik koleksiyon (toplu işlem için en pratik)

1. Aynı modelin tüm ürünlerine etiket verin: `model:borderline`
2. Otomatik koleksiyon oluşturun: koşul **Ürün etiketi = model:borderline**,
   handle **`model-borderline`**.
3. Kartlar koleksiyon sıralamasıyla gelir. Önek (`model:` / `model-`) blok
   ayarlarından değiştirilebilir.

## Blok ayarları

- **Açık olan ürünü de göster**: kapalıysa yalnızca *diğer* renkler listelenir;
  açıksa açık ürün çerçeve + "Selectat" etiketiyle gösterilir.
- **Stokta olmayan renkleri gizle**
- Grid / Carousel, masaüstü ve mobil kolon, boşluklar, mobilde kaydırma
- Kart: görsel oranı, hover'da ikinci görsel, marka, puan, hızlı ekle
- **Debug**: liste boşsa hangi kaynağın bulunduğunu gösterir (kurulumdan sonra kapatın).

Grupta başka ürün yoksa blok hiçbir şey göstermez.
