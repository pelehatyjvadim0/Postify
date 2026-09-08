"""Build the MVP brief with reportlab."""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("Telegram-MVP-для-согласования.pdf")
SHOTS = ROOT / "docs/development-loop/evidence/artifacts/2026-08-12-wave-6"
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
pdfmetrics.registerFont(TTFont("Arial", str(FONT_DIR / "Arial.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Bold", str(FONT_DIR / "Arial Bold.ttf")))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold")
W, H = 595.28, 841.89
LEFT, WIDTH = 50, 495.28
c = canvas.Canvas(str(OUT), pagesize=(W, H))
c.setTitle("Сервис планирования и публикации Telegram-постов")
c.setAuthor("AutoPostTG")
c.setSubject("Требования к первой версии и критерии MVP")
styles = {
    "body": ParagraphStyle("body", fontName="Arial", fontSize=10.5, leading=14.5, textColor=colors.HexColor("#202020")),
    "small": ParagraphStyle("small", fontName="Arial", fontSize=8.5, leading=11.5, textColor=colors.HexColor("#666666")),
    "h2": ParagraphStyle("h2", fontName="Arial-Bold", fontSize=13, leading=17, textColor=colors.black),
    "title": ParagraphStyle("title", fontName="Arial-Bold", fontSize=18, leading=23, textColor=colors.black),
}
y = 0


def para(text, style="body", gap=7, x=LEFT, width=WIDTH):
    global y
    p = Paragraph(text, styles[style])
    _, height = p.wrap(width, H)
    if y - height < 42:
        raise ValueError(f"Page overflow: {text[:70]}")
    p.drawOn(c, x, y - height)
    y -= height + gap


def start(number):
    global y
    c.setFillColor(colors.white)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFont("Arial", 8)
    c.setFillColor(colors.HexColor("#777777"))
    c.drawRightString(W - LEFT, 24, f"{number} / 2")
    y = H - 45


def heading(text):
    para(text, "h2", 7)


def divider():
    global y
    y -= 3
    c.setStrokeColor(colors.HexColor("#dddddd"))
    c.line(LEFT, y, W - LEFT, y)
    y -= 15


def shot(name, caption):
    global y
    width = 465
    height = width * 1000 / 1440
    x = LEFT + (WIDTH - width) / 2
    if y - height < 60:
        raise ValueError("Screenshot overflow")
    c.drawImage(ImageReader(str(SHOTS / name)), x, y - height,
                width=width, height=height, preserveAspectRatio=True)
    c.setStrokeColor(colors.HexColor("#dddddd"))
    c.rect(x, y - height, width, height, fill=0, stroke=1)
    y -= height + 5
    para(caption, "small", 11, x=x, width=width)


start(1)
para("Сервис планирования и публикации<br/>Telegram-постов", "title", 13)
heading("1. Задача")
para("Необходимо разработать web-сервис для подготовки предложений постов, их проверки редактором и публикации в Telegram по расписанию.")
heading("2. Генерация текстов")
para("Необходимо предусмотреть генерацию через Gemini 3.8. Точный API-идентификатор модели уточняется перед подключением.")
para("Тексты должны соответствовать теме и аудитории канала, звучать естественно, не содержать шаблонных оборотов и неподтверждённых фактов. Качество проверяется редактором на согласованной выборке материалов.")
heading("3. Планирование и проверка")
para("Система должна назначать предложению дату и время публикации и показывать его в UI. По каждому посту необходимо отображать текст, канал, дату, время, часовой пояс и статус.")
para("Редактор должен иметь возможность открыть пост и принять либо отклонить его. До принятия редактором публикация не выполняется.")
heading("4. Публикация")
para("Бот должен отправлять принятые посты в Telegram по расписанию. В UI необходимо показывать результат отправки или ошибку. Повторная обработка не должна создавать дубликаты публикаций.")
para("Порядок назначения дат и действия при пропущенном времени публикации необходимо согласовать отдельно.", "small")
divider()
heading("5. MVP — критерии первой версии")
para("Первая версия считается готовой, если:")
for n, text in enumerate([
    "Система генерирует предложения постов через согласованную модель Gemini и выводит их в UI.",
    "Редактор видит содержание, канал и запланированные дату и время каждого предложения до его принятия.",
    "Редактор может принять или отклонить пост; решение сохраняется и отображается в интерфейсе.",
    "Отклонённые и неподтверждённые посты не публикуются.",
    "Принятые посты отправляются в Telegram по расписанию без повторных публикаций.",
    "В UI видны статусы постов, результаты отправки и ошибки.",
    "На согласованной выборке редактор подтверждает естественность текстов и их готовность к публикации без существенной переработки.",
], 1):
    para(f"{n}. {text}", gap=5)
c.showPage()

start(2)
heading("6. Интерфейс")
para("Визуальная основа панели. Скриншоты содержат тестовые данные; состав полей и действий определяется требованиями первой версии.", "small", 9)
shot("desktop-review.png", "Проверка — список предложений постов для решения редактора.")
shot("desktop-queue.png", "Очередь — представление плана публикаций.")
c.save()
print(OUT)
