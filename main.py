import uvicorn
import datetime
from fastapi.security import HTTPBasic
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles
from models import SessionLocal, Booking
from fastapi import FastAPI, HTTPException, Form, Depends, Request
from mako.lookup import TemplateLookup
import requests
from Admin_Info import token, chat_id, secret
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date, timedelta

# -------------------- Планировщик очистки просроченных броней --------------------
def clean_expired_bookings():
    db = SessionLocal()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    deleted = db.query(Booking).filter(
        Booking.payment_status == 'pending',
        Booking.expires_at < now_utc
    ).delete()
    db.commit()
    db.close()
    if deleted:
        print(f"Удалено {deleted} просроченных неоплаченных броней")

scheduler = BackgroundScheduler()
scheduler.add_job(clean_expired_bookings, 'interval', hours=1)
scheduler.start()
# --------------------------------------------------------------------------------

secret_key = secret()
security = HTTPBasic()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()
template_lookup = TemplateLookup(directories=["templates"])
app.mount("/static", StaticFiles(directory="static"), name="static")

homes = [
    {"id": 1, "price_per_day": 1500, "distance_to_lift": 300, "rooms": 4, "pool": False,
     "img": "/static/img/home1.png",
     "img_room": ["/static/img/home1.png", "/static/img/img_1.png", "/static/img/img_2.png", "/static/img/img_3.png", "/static/img/img_4.png", "/static/img/img_5.png", "/static/img/img_6.png", "/static/img/img_7.png", "/static/img/img_8.png", "/static/img/img_9.png","/static/img/img_10.png"],
     "tv": True, "wifi": True, "batut": False, "rating": 5},
]

@app.get("/")
def root(request: Request):
    template = template_lookup.get_template("index.html")
    return HTMLResponse(template.render(homes=homes))

# ----- Проверка доступности дат и API для календаря -----
def is_home_available(home_id: int, check_in: date, check_out: date, db: Session):
    overlapping = db.query(Booking).filter(
        Booking.home_id == home_id,
        Booking.status == 'confirmed',   # только подтверждённые блокируют
        Booking.check_in < check_out,
        Booking.check_out > check_in
    ).first()
    return overlapping is None

@app.get("/api/blocked_dates/{home_id}")
def get_blocked_dates(home_id: int, db: Session = Depends(get_db)):
    bookings = db.query(Booking).filter(
        Booking.home_id == home_id,
        Booking.status == 'confirmed'
    ).all()
    blocked = []
    for b in bookings:
        delta = (b.check_out - b.check_in).days
        for i in range(delta):
            date_str = (b.check_in + timedelta(days=i)).isoformat()
            blocked.append(date_str)
    return {"blocked": blocked}
# ---------------------------------------------------------

@app.post("/booking")
def create_form(
    home_id: int = Form(...),
    check_in: str = Form(...),          # строка, а не date
    check_out: str = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(""),
    peoples: str = Form(...),
    early_checkin: bool = Form(False),
    late_checkout: bool = Form(False),
    parking: bool = Form(False),
    db: Session = Depends(get_db)
):
    # Преобразуем строки в даты
    try:
        check_in_date = datetime.datetime.strptime(check_in, '%Y-%m-%d').date()
        check_out_date = datetime.datetime.strptime(check_out, '%Y-%m-%d').date()
    except ValueError:
        raise HTTPException(400, "Неверный формат даты")

    # Проверяем доступность
    if not is_home_available(home_id, check_in_date, check_out_date, db):
        raise HTTPException(400, "Эти дни уже забронированы")

    days = (check_out_date - check_in_date).days
    if days <= 0:
        raise HTTPException(400, "Дата выезда должна быть позже даты заезда")
    if days < 2:
        raise HTTPException(400, "Минимальная длительность — 2 дня")

    home = next((h for h in homes if h["id"] == home_id), None)
    if not home:
        raise HTTPException(404, "Дом не найден")

    # Рассчитываем полную стоимость
    price = home["price_per_day"] * days
    if early_checkin: price += 1000
    if late_checkout: price += 1000
    if parking: price += 500

    booking = Booking(
        home_id=home_id,
        check_in=check_in_date,
        check_out=check_out_date,
        name=name,
        phone=phone,
        email=email,
        early_checkin=early_checkin,
        late_checkout=late_checkout,
        parking=parking,
        total_price=price,
        peoples=peoples,
        payment_status='pending',
        expires_at=datetime.datetime.now(datetime.timezone.utc) + timedelta(minutes=30)
    )
    db.add(booking)
    db.commit()

    # Формируем сообщение в Telegram
    addons = []
    if early_checkin: addons.append("🌅 Ранний заезд")
    if late_checkout: addons.append("🌙 Поздний выезд")
    if parking: addons.append("🅿️ Парковка")
    addons_str = ", ".join(addons) if addons else "нет"
    message = f"Новый заказ!\nДом №{home_id}\nИмя: {name}\nТелефон: {phone}\nДаты: {check_in} – {check_out}\nГостей: {peoples}\nДоп. услуги: {addons_str}\nПолная сумма: {price}₽\nДля подтверждения нужна предоплата 600₽"
    RostovHomes(message)
    return RedirectResponse(url=f"/success?booking_id={booking.id}", status_code=303)

# ----- Фейк-оплата (предоплата 600₽) -----
@app.get("/fake_pay/{booking_id}")
def fake_pay(booking_id: int, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Бронь не найдена")
    if booking.payment_status == 'paid':
        # уже оплачено
        return RedirectResponse(url=f"/success?booking_id={booking_id}")
    # Устанавливаем предоплату 600₽
    booking.prepaid_amount = 600
    booking.status = 'confirmed'
    booking.payment_status = 'paid'
    db.commit()
    RostovHomes(f"✅ Получена предоплата 600₽! Бронь #{booking.id} подтверждена. Даты закреплены.")
    return RedirectResponse(url=f"/success?booking_id={booking_id}")

@app.get("/success")
def success(booking_id: int = None, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id) if booking_id else None
    template = template_lookup.get_template("success.html")
    if not booking:
        return HTMLResponse(template.render(all=None))
    return HTMLResponse(template.render(all=booking))

@app.get("/booking")
def show_booking_form(request: Request, home_id: int = None):
    if home_id is None:
        raise HTTPException(400, "Не указан ID домика")
    home = next((h for h in homes if h["id"] == home_id), None)
    if not home:
        raise HTTPException(404, "Домик не найден")
    template = template_lookup.get_template("booking.html")
    return HTMLResponse(template.render(
        home_id=home_id,
        img_rooms=home["img_room"],
        price_per_day=home["price_per_day"]
    ))

def RostovHomes(message):
    t = token() if callable(token) else token
    cid = chat_id() if callable(chat_id) else chat_id
    url = f"https://api.telegram.org/bot{t}/sendMessage"
    data = {"chat_id": cid, "text": message}
    try:
        requests.post(url, json=data, timeout=10, proxies={"http": None, "https": None})
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

# ----- Админка и остальные маршруты (без изменений, только .get() заменён на db.get) -----
@app.get("/admin/{password}")
def admin(password, db: Session = Depends(get_db)):
    if password == secret_key:
        bookings = db.query(Booking).order_by(Booking.created_at.desc()).all()
        template = template_lookup.get_template("admin.html")
        return HTMLResponse(template.render(bookings=bookings, password=password))
    else:
        raise HTTPException(404)

@app.get("/admin/{password}/confirm/{booking_id}")
def confirm(password, booking_id, db: Session = Depends(get_db)):
    if password != secret_key: raise HTTPException(404)
    booking = db.get(Booking, booking_id)
    if not booking: raise HTTPException(404)
    booking.status = "confirmed"
    db.commit()
    return RedirectResponse(url=f"/admin/{password}", status_code=303)

@app.get("/admin/{password}/cancel/{booking_id}")
def cancel(password, booking_id, db: Session = Depends(get_db)):
    if password != secret_key: raise HTTPException(404)
    booking = db.get(Booking, booking_id)
    if not booking: raise HTTPException(404)
    booking.status = "cancelled"
    db.commit()
    return RedirectResponse(url=f"/admin/{password}", status_code=303)

@app.get("/login")
def login_page(request: Request):
    template = template_lookup.get_template("login.html")
    return HTMLResponse(template.render())

@app.post("/login")
def login_check(pin: str = Form(...)):
    if pin == secret_key:
        return RedirectResponse(url=f"/admin/{secret_key}", status_code=303)
    else:
        return RedirectResponse(url="/login", status_code=303)

@app.get("/track")
def track(booking_id: int = None, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id) if booking_id else None
    if not booking:
        raise HTTPException(404)
    template = template_lookup.get_template("track.html")
    return HTMLResponse(template.render(all=booking))

@app.get("/support")
def support_page(request: Request):
    template = template_lookup.get_template("support.html")
    return HTMLResponse(template.render())

@app.post("/support")
def support_send(
    name: str = Form(...),
    contact: str = Form(...),
    message: str = Form(...)
):
    msg = f"📩 Новое обращение!\nИмя: {name}\nКонтакты: {contact}\nВопрос: {message}"
    RostovHomes(msg)
    return RedirectResponse(url="/success", status_code=303)

reviews_data = [
    {"name": "Марина", "date": "12 мая 2026", "rating": 5, "text": "Отдыхали с семьёй, очень понравилось! Дом чистый, удобный, до моря рукой подать. Обязательно вернёмся.", "answer": "Спасибо, Марина! Ждём вас снова!"},
    {"name": "Алексей", "date": "3 мая 2026", "rating": 5, "text": "Хороший дом, но телевизор староват. А так всё отлично.", "answer": "Алексей, спасибо за отзыв! Телевизор уже заменили."},
    {"name": "Ольга", "date": "20 апреля 2026", "rating": 5, "text": "Превосходное место! Рекомендую."},
]

@app.get("/reviews")
def reviews_page(request: Request):
    template = template_lookup.get_template("reviews.html")
    return HTMLResponse(template.render(reviews=reviews_data))

if __name__ == "__main__":
    uvicorn.run(app)