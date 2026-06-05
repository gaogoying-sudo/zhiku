.PHONY: check deploy smoke release status progress sync-frontend

SMOKE_KEYWORD ?= appVersion
SMOKE_SN ?=

sync-frontend:
	cp deploy/frontend/index.html deploy/frontend/app.html

check:
	scripts/check_project.sh

deploy:
	python3 scripts/deploy_cloud.py

smoke:
	python3 scripts/smoke_cloud.py --keyword "$(SMOKE_KEYWORD)" $(if $(SMOKE_SN),--sn "$(SMOKE_SN)",)

release: check deploy smoke

status:
	python3 scripts/cloud_status.py

progress:
	scripts/progress_note.sh
