# Mandalina

Windows için "sürükle + Shift" dosya dönüştürücü ([Tangerine for Mac](https://tangerineformac.com)'ten esinlenildi).
Her şey bilgisayarda yerel olarak çalışır, hiçbir dosya internete yüklenmez.

**İndir:** [Mandalina.exe](https://github.com/gokhangeo/uzman/releases/download/mandalina-v1.1/Mandalina.exe)
(tek dosya, kurulum yok; [tüm sürümler](https://github.com/gokhangeo/uzman/releases))

## Kullanım

- **Sürükle + Shift:** Explorer'da bir dosyayı sürüklemeye başla, Shift'e bas. İmlecin etrafında bir çark açılır;
  dosyayı istediğin dilime bırak. Çıktı, orijinal dosyanın yanına kaydedilir.
- **Sağ tık:** Dosyaya sağ tıkla → "Mandalina ile dönüştür" → çarkta bir dilime tıkla.
  Windows 11'de önce "Daha fazla seçenek göster"e tıklaman (ya da Shift+F10) gerekir.
- Saat yanındaki turuncu simge: sağ tık menüsünü aç/kapat, Windows ile başlat, çıkış.

| Dosya türü | Seçenekler |
|---|---|
| Görsel | PNG, JPG, WEBP, PDF, ICO, BMP, TIFF, ZIP |
| Video | MP4, MOV, MKV, WEBM, GIF, MP3, WAV, ZIP |
| Ses | MP3, WAV, FLAC, M4A, OGG, OPUS, ZIP |
| PDF | DOCX, BİRLEŞTİR, PARÇALA, PNG, JPG, TXT, ZIP |
| Word | PDF, BİRLEŞTİR, DOCX, TXT, RTF, ODT, ZIP |
| Excel | PDF, XLSX, CSV, ODS, ZIP |
| PowerPoint | PDF, PNG, JPG, PPTX, ZIP |
| Diğer | ZIP, YOLU KOPYALA |

## Gereksinimler

- Windows 10/11
- Video/ses için `ffmpeg` (PATH'te ya da exe'nin yanında `ffmpeg.exe`): `winget install Gyan.FFmpeg`
- Word/Excel/PowerPoint dönüşümleri için Microsoft Office

## Geliştirme

```bat
pip install -r requirements.txt
python mandalina.py        :: doğrudan çalıştır
build.bat                  :: dist\Mandalina.exe (tek dosya) üretir
```

Kayıtlar: `%LOCALAPPDATA%\Mandalina\olaylar.log` ve `hata.log`.

### Yeni sürüm yayınlama

Exe'yi bilgisayarda derlemek gerekmez; GitHub Actions Windows'ta derler
([`.github/workflows/mandalina.yml`](../.github/workflows/mandalina.yml)).

1. Değişiklikleri `main`'e gönder. Yukarıdaki "İndir" bağlantısındaki sürüm etiketini de yenisiyle değiştir.
2. Yeni bir etiket gönder (bir öncekinden büyük olsun):
   ```bash
   git tag mandalina-v1.1
   git push origin mandalina-v1.1
   ```
3. Actions exe'yi derler ve `mandalina-v1.1` release'ine `Mandalina.exe` olarak yükler (release yoksa oluşturur).

Sadece denemek için: GitHub'da Actions → Mandalina → "Run workflow". Exe, çalışmanın sayfasında
"Mandalina" artifact'ı olarak indirilebilir; release'e dokunulmaz.

## Tasarım notları (değiştirmeden önce oku)

- **Shift algılama:** `App._poll` her 15 ms'de `GetAsyncKeyState` ile sol tuş + Shift'e bakar.
  Sürükleme eşiği aşıldığında Shift basılıysa (önceden basılı tutulsa bile) çark açılır.
- **Bırakma (drop):** Çark, saf ctypes ile yazılmış bir OLE `IDropTarget` (`OleDropTarget`) kaydeder.
  Dosya listesi `DragEnter`'da `CF_HDROP`'tan okunur ve çark dosya türüne göre yeniden çizilir.
  Her zaman `DROPEFFECT_COPY` döner, kaynak dosyaya dokunulmaz. `WM_DROPFILES` yedek yol olarak durur.
  - pywin32'nin COM sunucu katmanı (`win32com.server`) Python 3.14'te sürükleme sırasında çöküyor; kullanma.
  - COM geri çağrılarının içinde tkinter'a **dokunma** (Python "GIL" hatasıyla çöker).
    Geri çağrılar sadece `wheel.ole_events` listesine yazar; işleme `App.poll`'da yapılır.
  - Sürükleme sırasında Explorer'a COM ile soru sorma (seçili dosyalar vb.): Explorer meşgulken takılıyor
    ve bırakma kayboluyordu.
- **Dönüştürme ayrı işlemde:** `run_conversion` exe'yi `--convert FMT sonuc.json dosyalar...` ile yeniden çalıştırır.
  Office/pdf2docx çökse bile ana program ayakta kalır. Diğer thread'ler arayüze yalnızca `App.events` kuyruğuyla ulaşır.
- **Sağ tık menüsü:** `HKCU\Software\Classes\*\shell\Mandalina` (ve `Directory`). Çoklu seçimde Explorer her dosya
  için ayrı `--menu` işlemi başlatır; ilk işlem (mutex ile seçilen lider) diğerlerinin yollarını
  `%TEMP%\mandalina-menu.txt` üzerinden kısa süre toplar ve tek çark açar.
- Office dönüşümleri COM ile (`DispatchEx`); PowerPoint, kullanıcının açık sunumu varsa kapatılmaz.
- **BİRLEŞTİR sırası:** Dosyalar geldiği sırayla birleştirilir (sıralama yapılmaz). Explorer sürüklemede
  tutulan dosyayı listenin başına koyar, böylece tutulan PDF ilk sayfalar olur.
- **Otomatik güncelleme:** Sürüm, derlemede `version.txt` olarak exe'ye gömülür (`MANDALINA_VERSION`,
  Actions'ta etiketten gelir; yoksa `dev`). Açılıştan 5 sn sonra GitHub Releases'te daha büyük
  `mandalina-vX.Y` + `Mandalina.exe` aranır, exe'nin yanına indirilir, çalışan exe `Mandalina.eski.exe`
  olarak yeniden adlandırılıp yenisi yerine konur ve `--updated` ile yeniden başlatılır
  (`PYINSTALLER_RESET_ENVIRONMENT=1` şart). Süren dönüştürme varsa bitmesi beklenir. `dev` derlemeler ve
  `.py` olarak çalıştırma güncellenmez. Test için `MANDALINA_UPDATE_URL` ile sahte bir release listesi verilebilir.
  **Etiketteki sürüm ile exe'nin sürümü aynı olmalı**; olmazsa `SkipTag` ayarı sonsuz döngüyü engeller.
