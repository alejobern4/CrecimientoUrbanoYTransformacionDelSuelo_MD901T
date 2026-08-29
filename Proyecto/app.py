from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/etapa1")
def etapa1():
    return render_template("etapa1.html")