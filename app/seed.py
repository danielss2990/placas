"""Dados de demonstração (apenas se o banco estiver vazio)."""
from datetime import date, timedelta

from .models import Debt, DebtType, Vehicle, db
from .recognition import classify


def seed_demo_data() -> None:
    if Vehicle.query.first():
        return
    today = date.today()
    vehicles = [
        ("BRA2E19", "Maria Souza", "Fiat Argo", "Branco", 2021, [
            (DebtType.IPVA, f"IPVA {today.year}", 185_000, today + timedelta(days=20)),
            (DebtType.LICENCIAMENTO, f"Licenciamento {today.year}", 16_090, today - timedelta(days=45)),
            (DebtType.MULTA, "Excesso de velocidade até 20%", 13_016, today - timedelta(days=10)),
        ]),
        ("ABC1234", "João Pereira", "VW Gol", "Prata", 2015, [
            (DebtType.IPVA, f"IPVA {today.year - 1}", 98_000, today - timedelta(days=200)),
            (DebtType.MULTA, "Estacionar em local proibido", 19_523, today + timedelta(days=15)),
            (DebtType.ESTACIONAMENTO, "Zona Azul - 3 horas", 1_500, today - timedelta(days=2)),
        ]),
        ("RIO4F56", "Ana Lima", "Honda Civic", "Preto", 2023, [
            (DebtType.PEDAGIO, "Pedágio free flow", 2_190, today - timedelta(days=5)),
        ]),
    ]
    for plate, owner, model, color, year, debts in vehicles:
        v = Vehicle(plate=plate, plate_type=classify(plate), owner_name=owner,
                    model=model, color=color, year=year)
        for t, desc, amount, due in debts:
            v.debts.append(Debt(type=t, description=desc, amount_cents=amount, due_date=due))
        db.session.add(v)
    db.session.commit()
