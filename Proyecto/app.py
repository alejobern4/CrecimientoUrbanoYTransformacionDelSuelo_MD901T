from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/etapa1")
def etapa1():
    return render_template("etapa1.html")

@app.route("/etapa2")
def etapa2():
    return render_template("etapa2.html")