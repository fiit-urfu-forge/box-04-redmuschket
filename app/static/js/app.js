// CertGuard — минимальный vanilla JS.
// Блокируем кнопку отправки формы, чтобы избежать двойной загрузки файла.
document.addEventListener('submit', function (event) {
    const form = event.target;
    const button = form.querySelector('button[type="submit"]');
    if (button) {
        button.disabled = true;
        button.dataset.original = button.textContent;
        button.textContent = 'Обработка…';
        // Возвращаем кнопку, если страница не перезагрузилась (на всякий случай).
        setTimeout(function () {
            button.disabled = false;
            if (button.dataset.original) {
                button.textContent = button.dataset.original;
            }
        }, 15000);
    }
});
