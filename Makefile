.PHONY: test demo weekly universe prices regime build up down logs shell

test:            ## Offline-Tests
	python3 -m unittest discover -s tests -v

demo:            ## Kompletter Wochenlauf mit synthetischen Daten (ohne Netz)
	python3 -m satellit weekly --demo --no-push

weekly:          ## Echter Wochenlauf lokal (ohne Push)
	python3 -m satellit weekly --no-push

universe:        ## Konstituenten laden und prüfen
	python3 -m satellit universe --force --check

prices:          ## Kurs-Cache aktualisieren
	python3 -m satellit prices

regime:          ## US-Ampel-Skills ausführen
	python3 -m satellit regime

build:           ## Docker-Image bauen
	docker compose build

up:              ## Scheduler-Container starten
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

run-weekly:      ## Einmaliger Wochenlauf im Container (mit Push)
	docker compose run --rm satellit weekly

shell:
	docker compose run --rm --entrypoint bash satellit
