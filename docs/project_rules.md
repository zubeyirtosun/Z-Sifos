# Project Rules

## 1. Vizyon ve Kurallar (Modüler AI)
- **Düşük Kaynak Tüketimi:** Geliştirilen sistem "en küçük", "en performanssız" cihazları veya limitli kaynakları göz önünde bulundurularak yapılmalıdır.
- **Modülerlik ("Eklenti" Mantığı):** Yapay zekanın "hatırlama" (Memory), "internete erişim", "kod çalıştırma" gibi özellikleri tamamen takılıp-çıkarılabilir (plugin) mimarisinde olmalıdır. Çekirdek motor (core engine) mümkün olduğunca sade tutulmalıdır.
- **Provider (Sağlayıcı) Bağımsızlığı:** Başlangıçta kolaylık için **Ollama** kullanılacak olsa da, sistem Ollama'ya "sıkı sıkıya bağımlı" (tightly coupled) olmamalıdır. HuggingFace üzerinden indirilen `.gguf` vb. türevleri direkt olarak `llama.cpp` eklentileri (veya kütüphaneleri) aracılığıyla da sisteme dahil edilebilmesi planlanıp, mimari ona göre tasarlanmalıdır.
- **Kalıcı ve Açık Veritabanı:** Hafıza (memory) ve yapılandırmalar (konfigürasyonlar) açık kaynaklı olan **SQLite** (ve gerektiğinde ölçeklenebilir olması için SQLAlchemy ORM tabanlı) altyapısında tutulacaktır.
- **Kod Optimizasyonu ve Güncelleme Kuralı:** Kod, modüler, performans ve sürdürülebilirlik öncelikli şekilde yazılmalı; yapılan güncellemeler belgelenmeli ve optimizasyonlar sürekli takip edilmelidir.

## 2. Devamlılık Kuralı (ÖNEMLİ)
> ❗ Başka bir yapay zeka sisteme dahil olduğunda veya yeni bir sohbet başlatıldığında; bu `docs/` dizinindeki tüm dosyalar her aşamada **GÜNCEL TUTULACAKTIR**.
> Yapılan değişiklikler, eklenen özellikler, tamamlanan / askıda olan durumlar aksatılmadan `docs/progress_log.md` içerisine yazılacaktır. Hiçbir adım atlanmayacaktır.
