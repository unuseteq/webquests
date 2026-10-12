from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import html
import json
import mimetypes
import re
import uuid


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "games.json"
UPLOAD_DIR = ROOT / "uploads"
MAX_IMAGE_SIZE = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def load_games():
    if not DATA_FILE.exists():
        return []
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def escape(value):
    return html.escape(str(value), quote=True)


def render_catalog():
    source = (ROOT / "catalog.html").read_text(encoding="utf-8")
    additions = []
    details = []
    for index, game in enumerate(load_games(), start=1):
        detail_id = f"added-game-{index}"
        image = escape(game["image"])
        name = escape(game["name"])
        genre = escape(game["genre"])
        developer = escape(game["developer"])
        description = escape(game["description"])
        price = escape(game["price"])
        additions.append(f'''                <article class="game-card game-card--catalog">
                    <a class="game-card__art-link" href="#{detail_id}">
                        <img alt="Обложка игры {name}" class="game-card__image" src="{image}"/>
                    </a>
    <div class="game-card__body">
                        <div class="game-card__meta"><span>{genre}</span></div>
                        <h2 class="game-card__title">{name}</h2>
                        <p class="game-card__developer">{developer}</p>
                        <p class="game-card__description">{description}</p>
                        <div class="game-card__bottom">
                            <span class="price">{price} ₽</span>
                            <a class="button button--lime button--small" href="#{detail_id}">
                                Подробнее <span aria-hidden="true">↗</span>
                            </a>
                        </div>
    </div>
</article>''')
        details.append(f'''                <article class="game-detail" id="{detail_id}">
                    <img alt="Обложка игры {name}" src="{image}"/>
                    <div>
                        <p class="eyebrow">{genre} · {developer}</p>
                        <h2>{name}</h2>
                        <p>{description}</p>
                        <div class="game-detail__bottom">
                            <span class="price">{price} ₽</span>
                            <a class="text-link" href="#catalog-list">Назад к каталогу <span aria-hidden="true">↗</span></a>
                        </div>
                    </div>
                </article>''')

    grid_end = "            </div>\n            <div aria-live=\"polite\" class=\"game-details\">"
    if grid_end in source and additions:
        source = source.replace(grid_end, "\n".join(additions) + "\n" + grid_end, 1)
    details_end = "            </div>\n        </main>"
    if details_end in source and details:
        source = source.replace(details_end, "\n".join(details) + "\n" + details_end, 1)
    return source.encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/catalog.html":
            body = render_catalog()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/add-game":
            self.send_error(404)
            return
        try:
            self.handle_add_game()
        except (ValueError, KeyError, OSError) as error:
            self.send_error(400, str(error))

    def handle_add_game(self):
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            raise ValueError("Ожидается отправка формы с изображением.")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_IMAGE_SIZE + 1024 * 1024:
            raise ValueError("Размер отправленных данных превышает 9 МБ.")

        from email.parser import BytesParser
        from email.policy import default

        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n"
            + self.rfile.read(length)
        )
        fields = {}
        image_part = None
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "cover":
                image_part = part
            elif name:
                field_data = part.get_payload(decode=True) or b""
                fields[name] = field_data.decode("utf-8-sig").strip()

        required = ("game-name", "genre", "developer", "description", "price")
        if any(not fields.get(key) for key in required):
            raise ValueError("Заполните все поля формы.")
        if not re.fullmatch(r"\d{1,9}(?:\.\d{1,2})?", fields["price"]):
            raise ValueError("Укажите корректную цену.")
        if image_part is None or not image_part.get_filename():
            raise ValueError("Выберите файл обложки.")
        image_data = image_part.get_payload(decode=True) or b""
        image_type = image_part.get_content_type()
        if not image_data or len(image_data) > MAX_IMAGE_SIZE:
            raise ValueError("Обложка должна быть не больше 8 МБ.")
        if image_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError("Формат обложки: JPG, PNG, GIF или WebP.")

        extension = mimetypes.guess_extension(image_type) or ".img"
        filename = f"{uuid.uuid4().hex}{extension}"
        UPLOAD_DIR.mkdir(exist_ok=True)
        (UPLOAD_DIR / filename).write_bytes(image_data)
        game = {
            "name": fields["game-name"],
            "genre": fields["genre"],
            "developer": fields["developer"],
            "description": fields["description"],
            "price": fields["price"],
            "image": f"uploads/{filename}",
        }
        DATA_FILE.parent.mkdir(exist_ok=True)
        games = load_games()
        games.append(game)
        DATA_FILE.write_text(json.dumps(games, ensure_ascii=False, indent=2), encoding="utf-8")
        self.send_response(303)
        self.send_header("Location", "/catalog.html")
        self.end_headers()


if __name__ == "__main__":
    print("BestGames: http://localhost:5500")
    ThreadingHTTPServer(("127.0.0.1", 5500), Handler).serve_forever()
