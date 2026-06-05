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

delegate-check:
	python3 scripts/local_agent_delegate.py --mode run --command check --task "本地检查并总结"

delegate-smoke:
	python3 scripts/local_agent_delegate.py --mode run --command smoke --smoke-keyword "$(SMOKE_KEYWORD)" $(if $(SMOKE_SN),--smoke-sn "$(SMOKE_SN)",) --task "线上冒烟并总结"

delegate-status:
	python3 scripts/local_agent_delegate.py --mode run --command status --task "云端状态并总结"
