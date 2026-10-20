# Bu repo hakkında

- Her proje kök dizinde **kendi klasöründe** durur (ör. `mandalina/`). Yeni proje = yeni klasör + kendi `README.md`'si.
  Kök `README.md`'deki tabloya da bir satır ekle.
- Kullanıcı Türkçe konuşur ve Windows kullanır. Arayüz metinleri Türkçe olsun.
- Derlenmiş dosyaları (exe vb.) commit'leme; her projenin `.gitignore`'u bunları dışlar.
  Derleme adımları projenin `README.md`'sinde ve varsa `build.bat` içindedir.
  Hazır exe'ler GitHub Releases'e `<proje>-vX.Y` etiketiyle yüklenir (ör. `mandalina-v1.0`).
  Exe'ler GitHub Actions'ta derlenir (`.github/workflows/<proje>.yml`, Windows runner); bu yüzden Linux'taki
  bulut oturumlarından da yeni sürüm çıkarılabilir. Yeni sürüm: `git tag mandalina-v1.1 && git push origin mandalina-v1.1`
  → Actions derler ve exe'yi o etiketin release'ine yükler. Etiket göndermeden önce kullanıcıya sor;
  var olan release'leri silme/üzerine yazma.
- Bir projeyi değiştirmeden önce o projenin `README.md`'sindeki "Tasarım notları" bölümünü oku.
