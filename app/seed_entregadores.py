"""Popula a tabela de entregadores com os nomes iniciais."""
from app.database import init_db
from app.models import listar_entregadores, criar_entregador

NOMES = [
    "Andre Oliveira",
    "Ruben",
    "Breno Farias",
    "Fredy Gonzales",
    "Tanner Castro",
    "Uziel Alex",
    "Matheus Guedes",
    "Mayke Martins",
    "Carlos Alexandre",
    "Beatriz Araújo",
    "Matheus Oliveira",
    "Luiz Gustavo",
    "Rafael Gama",
    "Sergio Sullivan",
    "André Ferreira",
    "Thiago Felipe Weckner",
    "Isaac Costa",
    "Felipe Souza",
]

if __name__ == "__main__":
    init_db()
    existentes = {e["nome"].lower() for e in listar_entregadores(ativos_apenas=False)}
    for i, nome in enumerate(NOMES):
        if nome.lower() not in existentes:
            criar_entregador(nome, ordem=i * 10)
            print(f"  ✓ {nome}")
        else:
            print(f"  ~ {nome} já existe")
    print("Concluído!")
