(function () {
    if (!window.Vue || !window.Vue.createApp) return;

    function injectPowerRecipeFilterControl() {
        const labels = Array.from(document.querySelectorAll('label.filter-label'));
        const keywordLabel = labels.find((label) => (label.textContent || '').includes('步骤/食材关键词'));
        if (!keywordLabel) return;
        const keywordCol = keywordLabel.closest('.col-xl-4, .col-md-6, [class*="col-"]');
        if (!keywordCol || keywordCol.parentElement.querySelector('[data-power-recipe-filter="true"]')) return;

        keywordCol.classList.remove('col-xl-4');
        keywordCol.classList.add('col-xl-3');

        const filterCol = document.createElement('div');
        filterCol.className = 'col-xl-3 col-md-6';
        filterCol.setAttribute('data-power-recipe-filter', 'true');
        filterCol.innerHTML = `
            <label class="filter-label">人工选择菜谱</label>
            <select class="form-select form-select-sm" v-model="powerDiagnosisFilters.recipeKey" @change="ensurePowerDiagnosisCookVisible">
                <option value="">全部菜谱</option>
                <option v-for="r in powerDiagnosisRecipeOptions" :key="r.key" :value="r.key">
                    {{ r.name }}（{{ r.count }}次）
                </option>
            </select>
        `;
        keywordCol.insertAdjacentElement('afterend', filterCol);
    }

    const originalCreateApp = window.Vue.createApp;
    window.Vue.createApp = function (options, ...args) {
        injectPowerRecipeFilterControl();

        if (options && typeof options.data === 'function') {
            const originalData = options.data;
            options.data = function (...dataArgs) {
                const state = originalData.apply(this, dataArgs);
                state.powerDiagnosisFilters = state.powerDiagnosisFilters || {};
                if (!Object.prototype.hasOwnProperty.call(state.powerDiagnosisFilters, 'recipeKey')) {
                    state.powerDiagnosisFilters.recipeKey = '';
                }
                return state;
            };
        }

        const originalComputed = options.computed || {};
        options.computed = {
            ...originalComputed,
            powerDiagnosisRecipeOptions() {
                const map = new Map();
                (this.cookTemperatureCooks || []).forEach((item) => {
                    const key = this.cookTemperatureRecipeKey ? this.cookTemperatureRecipeKey(item) : String(item?.cook?.recipe_id || item?.cook?.recipe_name || 'unknown');
                    const name = item?.cook?.recipe_name || item?.cook?.recipe_id || '未命名菜谱';
                    const current = map.get(key) || { key, name, count: 0 };
                    current.count += 1;
                    map.set(key, current);
                });
                return Array.from(map.values()).sort((a, b) => b.count - a.count || String(a.name).localeCompare(String(b.name)));
            },
            filteredPowerDiagnosisCooks() {
                const minEnergy = this.normalizedPowerMinEnergyKwh;
                const recipeKey = String(this.powerDiagnosisFilters?.recipeKey || '');
                return (this.cookTemperatureCooks || []).filter((item) => {
                    if (recipeKey && this.cookTemperatureRecipeKey && this.cookTemperatureRecipeKey(item) !== recipeKey) return false;
                    const actual = Number(item?.summary?.actual_energy_kwh || 0);
                    return !minEnergy || actual >= minEnergy;
                });
            },
        };

        const originalMethods = options.methods || {};
        options.methods = {
            ...originalMethods,
            ensurePowerDiagnosisCookVisible() {
                this.$nextTick(() => {
                    const rows = this.filteredPowerDiagnosisCooks || [];
                    if (!rows.length) {
                        this.selectedCookTemperatureKey = '';
                        this.selectedCookTemperatureIndex = 0;
                        return;
                    }
                    const found = rows.some((item, idx) => this.cookTemperatureKey(item, idx) === this.selectedCookTemperatureKey);
                    if (!found && this.selectCookTemperature) this.selectCookTemperature(rows[0], 0);
                });
            },
        };

        return originalCreateApp.call(this, options, ...args);
    };
})();
