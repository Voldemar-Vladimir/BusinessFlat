import uvicorn
import datetime
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles
from models import SessionLocal, Booking
from fastapi import FastAPI, HTTPException, Form, Depends, Request
from pydantic import BaseModel, Field
from mako.lookup import TemplateLookup
import requests
from Admin_Info import token,chat_id,secret

secret_key = secret()
toke=token()
chat_id=chat_id()
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

@app.post("/booking")
def create_form(
    home_id: int = Form(...),
    check_in: datetime.date = Form(...),
    check_out: datetime.date = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(""),
    mini_bar: bool = Form(False),
    transfer: bool = Form(False),
    peoples: str = Form(...),
    early_checkin: bool = Form(False),
    late_checkout: bool = Form(False),
    parking: bool = Form(False),
    db: Session = Depends(get_db)
):
    days = (check_out - check_in).days
    if days <= 0:
        raise HTTPException(400, "Дата выезда должна быть позже даты заезда")
    if days < 2:
        raise HTTPException(400, "Минимальная длительность — 2 дня")

    home = next((h for h in homes if h["id"] == home_id), None)
    if not home:
        raise HTTPException(404, "Дом не найден")

    price = home["price_per_day"] * days
    if mini_bar:
        price += 4000
    if transfer:
        price += 1500
    if early_checkin:
        price += 1000
    if late_checkout:
        price += 1000
    if parking:
        price += 500
    booking = Booking(
        home_id=home_id,
        check_in=check_in,
        check_out=check_out,
        name=name,
        phone=phone,
        email=email,
        mini_bar=mini_bar,
        transfer=transfer,
        total_price=price,
        peoples=peoples
    )
    db.add(booking)
    db.commit()
    addons = []
    if early_checkin: addons.append("🌅 Ранний заезд")
    if late_checkout: addons.append("🌙 Поздний выезд")
    if parking: addons.append("🅿️ Парковка")
    addons_str = ", ".join(addons) if addons else "нет"
    message = f"Новый заказ!\nДом №{home_id}\nИмя: {name}\nТелефон: {phone}\nДаты: {check_in} – {check_out}\nГостей: {peoples}\nДоп. услуги: {addons_str}\nСумма: {price}₽"
    RostovHomes(message)
    return RedirectResponse(url=f"/success?booking_id={booking.id}", status_code=303)

@app.get("/success")
def success(booking_id: int = None, db: Session = Depends(get_db)):
    all = db.query(Booking).get(booking_id) if booking_id else None
    template = template_lookup.get_template("success.html")
    if not all:
        return HTMLResponse(template.render(all=None))
    return HTMLResponse(template.render(all=all))

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
    token = "8601793998:AAH0Kqg5_eR9rccweqscC3EVAIiwHovmq7A"
    chat_id = "5977647337"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": message}
    try:
        requests.post(url, json=data, timeout=10, proxies={"http": None, "https": None})
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

@app.get("/admin/{password}")
def admin(password,db: Session = Depends(get_db)):
    if password == secret_key:
        bookings=db.query(Booking).order_by(Booking.created_at.desc()).all()
        template = template_lookup.get_template("admin.html")
        return HTMLResponse(template.render(bookings=bookings,password=password))
    else:
        raise HTTPException(404)

@app.get("/admin/{password}/confirm/{booking_id}")
def confirm(password,booking_id, db: Session = Depends(get_db)):
    if password != secret_key: raise HTTPException(404)
    booking = db.query(Booking).get(booking_id)
    if not booking: raise HTTPException(404)
    booking.status = "confirmed"
    db.commit()
    return RedirectResponse(url=f"/admin/{password}", status_code=303)

@app.get("/admin/{password}/cancel/{booking_id}")
def cancel(password,booking_id, db: Session = Depends(get_db)):
    if password != secret_key: raise HTTPException(404)
    booking = db.query(Booking).get(booking_id)
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
    all = db.query(Booking).get(booking_id) if booking_id else None
    if not all:
        raise HTTPException(404)
    template = template_lookup.get_template("track.html")
    return HTMLResponse(template.render(all=all))

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