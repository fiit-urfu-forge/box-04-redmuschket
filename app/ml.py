"""TF-IDF поиск ближайшего сертификата.

Используется ТОЛЬКО scikit-learn (TfidfVectorizer + NearestNeighbors) —
нейросетевые эмбеддинги запрещены spec_kit.md.

Модель хранится на диске в виде .pkl. При повреждении/отсутствии файлов
система переходит в деградированный режим: операция `verify` недоступна,
но выпуск сертификатов продолжает работать.
"""
from __future__ import annotations

import os
import threading

import joblib
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

from app.config import get_settings
from app.logging_config import logger
from app.models import (
    AdminNotification,
    Certificate,
    CertificateStatus,
    Company,
    Severity,
)
from app.pdf_utils import read_pdf_text_from_path

settings = get_settings()


def sparse_row_to_json(row: csr_matrix) -> dict:
    """Сериализует разреженный TF-IDF вектор в JSON (плотные массивы запрещены)."""
    coo = row.tocoo()
    return {
        "indices": [int(i) for i in coo.col],
        "values": [float(v) for v in coo.data],
        "size": int(row.shape[1]),
    }


def _notify_admin(db, ntype: str, severity: Severity, message: str,
                  related_id: int | None = None) -> None:
    """Создаёт системное уведомление для администратора."""
    db.add(
        AdminNotification(
            type=ntype,
            severity=severity.value,
            message=message,
            related_entity_id=related_id,
        )
    )


class ModelStore:
    """Хранит обученные модели в памяти и синхронизирует их с диском."""

    def __init__(self) -> None:
        self.vectorizer: TfidfVectorizer | None = None
        self.nn: NearestNeighbors | None = None
        self.cert_ids: list[int] = []
        self.degraded: bool = False
        self._lock = threading.Lock()

    # --- пути к файлам моделей --------------------------------------------
    @property
    def tfidf_path(self) -> str:
        return os.path.join(settings.models_dir, "tfidf.pkl")

    @property
    def nn_path(self) -> str:
        return os.path.join(settings.models_dir, "nn.pkl")

    # --- состояние ---------------------------------------------------------
    def is_ready(self) -> bool:
        return (
            self.vectorizer is not None
            and self.nn is not None
            and len(self.cert_ids) > 0
        )

    def _clear(self) -> None:
        self.vectorizer = None
        self.nn = None
        self.cert_ids = []
        for path in (self.tfidf_path, self.nn_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:  # pragma: no cover
                pass

    # --- загрузка / сохранение --------------------------------------------
    def load(self) -> None:
        """Пробует загрузить модели при старте приложения."""
        if not (os.path.exists(self.tfidf_path) and os.path.exists(self.nn_path)):
            logger.info("Файлы моделей не найдены — требуется обучение (retrain)")
            self.degraded = True
            return
        try:
            self.vectorizer = joblib.load(self.tfidf_path)
            bundle = joblib.load(self.nn_path)
            self.nn = bundle["nn"]
            self.cert_ids = list(bundle["cert_ids"])
            self.degraded = False
            logger.info("Модели загружены: %d сертификатов в индексе", len(self.cert_ids))
        except Exception as exc:
            # EOFError, UnpicklingError, KeyError — файл повреждён.
            logger.critical("Файлы моделей повреждены, переход в деградированный режим: %s", exc)
            self.vectorizer = None
            self.nn = None
            self.cert_ids = []
            self.degraded = True

    def _save(self) -> None:
        os.makedirs(settings.models_dir, exist_ok=True)
        joblib.dump(self.vectorizer, self.tfidf_path)
        joblib.dump({"nn": self.nn, "cert_ids": self.cert_ids}, self.nn_path)

    # --- обучение ----------------------------------------------------------
    def rebuild(self, db) -> int:
        """Переобучает TF-IDF и NearestNeighbors с нуля по активным сертификатам.

        Возвращает число проиндексированных сертификатов.
        Повреждённые/недоступные PDF помечаются status='damaged'.
        Пустой корпус -> fit не вызывается, индекс очищается.
        """
        with self._lock:
            certs = (
                db.query(Certificate)
                .join(Company, Certificate.company_id == Company.id)
                .filter(Certificate.status == CertificateStatus.active.value)
                .filter(Company.is_active.is_(True))
                .order_by(Certificate.id)
                .all()
            )

            corpus: list[str] = []
            valid_certs: list[Certificate] = []
            for cert in certs:
                try:
                    text = read_pdf_text_from_path(cert.pdf_path)
                except FileNotFoundError:
                    logger.error("Certificate %s: PDF file corrupted or missing", cert.id)
                    cert.status = CertificateStatus.damaged.value
                    _notify_admin(
                        db, "corrupted_certificate", Severity.critical,
                        f"PDF сертификата id={cert.id} отсутствует на диске", cert.id,
                    )
                    continue
                except Exception as exc:
                    logger.error("Certificate %s: PDF unreadable: %s", cert.id, exc)
                    cert.status = CertificateStatus.damaged.value
                    _notify_admin(
                        db, "corrupted_certificate", Severity.critical,
                        f"PDF сертификата id={cert.id} повреждён", cert.id,
                    )
                    continue
                corpus.append(text)
                valid_certs.append(cert)

            if not corpus:
                # Пустой корпус — fit не вызываем (раздел 02 spec_kit).
                logger.info("Корпус пуст — модель не обучается")
                self._clear()
                self.degraded = False
                db.commit()
                return 0

            vectorizer = TfidfVectorizer(max_features=settings.tfidf_max_features)
            matrix = vectorizer.fit_transform(corpus)

            n_neighbors = min(max(settings.nn_neighbors, 1), len(valid_certs))
            nn = NearestNeighbors(metric="cosine", n_neighbors=n_neighbors)
            nn.fit(matrix)

            # Сохраняем разреженный вектор каждого сертификата в БД.
            for i, cert in enumerate(valid_certs):
                cert.tfidf_vector = sparse_row_to_json(matrix.getrow(i))

            self.vectorizer = vectorizer
            self.nn = nn
            self.cert_ids = [c.id for c in valid_certs]
            self.degraded = False
            self._save()
            db.commit()
            logger.info("Модель переобучена: %d сертификатов", len(valid_certs))
            return len(valid_certs)

    # --- поиск -------------------------------------------------------------
    def query(self, text: str) -> tuple[int | None, float]:
        """Ищет ближайший сертификат для текста подозрительного документа.

        Возвращает (certificate_id | None, similarity_score в диапазоне 0..1).
        Если общего словаря нет — (None, 0.0).
        """
        if not self.is_ready():
            raise RuntimeError("Модель не готова")

        vec = self.vectorizer.transform([text])
        if vec.nnz == 0:
            # Подозрительный документ не содержит ни одного известного слова.
            return None, 0.0

        n_neighbors = min(self.nn.n_neighbors, len(self.cert_ids))
        distances, indices = self.nn.kneighbors(vec, n_neighbors=n_neighbors)
        best_idx = int(indices[0][0])
        best_distance = float(distances[0][0])
        similarity = max(0.0, min(1.0, 1.0 - best_distance))
        return self.cert_ids[best_idx], similarity


# Глобальный экземпляр — один на процесс.
model_store = ModelStore()
