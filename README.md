# CNJ Automation Project

Bu proje CNJ (Conselho Nacional de Justiça) sisteminde otomatik işlemler gerçekleştirmek için geliştirilmiştir.

## Kurulum

1. Python virtual environment oluşturun:
```bash
python -m venv venv
```

2. Virtual environment'ı aktifleştirin:
```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. Gerekli paketleri yükleyin:
```bash
pip install -r requirements.txt
```

4. Environment variables dosyasını oluşturun:
```bash
cp .env.example .env
```

5. `.env` dosyasındaki değerleri kendi bilgilerinizle güncelleyin:
   - `TWOCAPTCHA_API_KEY`: 2Captcha servisinden aldığınız API key
   - `USER_PROFILE_DIR`: Chrome user profile dizininizin yolu
   - `DEFAULT_CPF`: Test için kullanılacak CPF numarası
   - `HEADLESS`: Browser'ı gizli modda çalıştırıp çalıştırmama

## Kullanım

```bash
python cnj_automation.py
```

## Gereksinimler

- Python 3.7+
- Chrome/Chromium browser
- 2Captcha hesabı (captcha çözümü için)

## Güvenlik

- `.env` dosyası Git'e yüklenmez ve API key'leriniz gizli kalır
- Lütfen API key'lerinizi paylaşmayın

## Lisans

Bu proje eğitim amaçlı geliştirilmiştir.