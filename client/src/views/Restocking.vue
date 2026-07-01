<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card budget-card">
      <div class="budget-header">
        <label for="budget-slider" class="budget-label">{{ t('restocking.budgetLabel') }}</label>
        <span class="budget-value">{{ formatCurrency(budget, currentCurrency) }}</span>
      </div>
      <input
        id="budget-slider"
        type="range"
        class="budget-slider"
        min="1000"
        max="100000"
        step="1000"
        v-model.number="budget"
        @input="onBudgetInput"
      />
      <div class="budget-range-labels">
        <span>{{ formatCurrency(1000, currentCurrency) }}</span>
        <span>{{ formatCurrency(100000, currentCurrency) }}</span>
      </div>
    </div>

    <div v-if="successMessage" class="success-banner">
      <span>{{ successMessage }}</span>
      <router-link to="/orders" class="success-link">{{ t('restocking.viewInOrders') }}</router-link>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.summary.budget') }}</div>
          <div class="stat-value">{{ formatCurrency(recommendations.budget, currentCurrency) }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.summary.recommendedCost') }}</div>
          <div class="stat-value">{{ formatCurrency(recommendations.total_cost, currentCurrency) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.summary.remainingBudget') }}</div>
          <div class="stat-value">{{ formatCurrency(recommendations.remaining_budget, currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.summary.itemsRecommended') }}</div>
          <div class="stat-value">{{ items.length }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.table.item') }} ({{ items.length }})</h3>
        </div>

        <div v-if="items.length === 0" class="empty-state">
          {{ t('restocking.noRecommendations') }}
        </div>
        <template v-else>
          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th>{{ t('restocking.table.item') }}</th>
                  <th>{{ t('restocking.table.category') }}</th>
                  <th>{{ t('restocking.table.trend') }}</th>
                  <th>{{ t('restocking.table.shortfall') }}</th>
                  <th>{{ t('restocking.table.recommendedQty') }}</th>
                  <th>{{ t('restocking.table.unitCost') }}</th>
                  <th>{{ t('restocking.table.lineTotal') }}</th>
                  <th>{{ t('restocking.table.leadTime') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in items" :key="item.item_sku">
                  <td>
                    <div class="item-name">{{ translateProductName(item.item_name) }}</div>
                    <div class="item-sku">{{ item.item_sku }}</div>
                  </td>
                  <td>{{ item.category }}</td>
                  <td>
                    <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                  </td>
                  <td>{{ item.shortfall.toLocaleString() }}</td>
                  <td>
                    <strong>{{ item.quantity.toLocaleString() }}</strong>
                    <span v-if="item.partial" class="badge warning partial-badge">
                      {{ t('restocking.partial') }}
                    </span>
                    <div v-if="item.partial" class="partial-note">
                      {{ t('restocking.qtyOfShortfall', { qty: item.quantity.toLocaleString(), shortfall: item.shortfall.toLocaleString() }) }}
                    </div>
                  </td>
                  <td>{{ formatCurrency(item.unit_cost, currentCurrency) }}</td>
                  <td><strong>{{ formatCurrency(item.line_total, currentCurrency) }}</strong></td>
                  <td>{{ t('restocking.leadTimeDays', { days: item.lead_time_days }) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="recommendations.skipped_items > 0" class="skipped-note">
            {{ t('restocking.skippedItemsNote', { count: recommendations.skipped_items }) }}
          </div>
        </template>

        <div class="place-order-row">
          <button
            class="place-order-btn"
            :disabled="loading || submitting || items.length === 0"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName, currentLocale } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const successMessage = ref(null)
    const budget = ref(25000)
    const recommendations = ref({
      budget: 0,
      total_cost: 0,
      remaining_budget: 0,
      skipped_items: 0,
      recommendations: []
    })

    let debounceTimer = null

    const items = computed(() => recommendations.value.recommendations || [])

    const loadRecommendations = async () => {
      try {
        loading.value = true
        error.value = null
        recommendations.value = await api.getRestockRecommendations(budget.value)
      } catch (err) {
        error.value = 'Failed to load restock recommendations: ' + err.message
      } finally {
        loading.value = false
      }
    }

    const onBudgetInput = () => {
      successMessage.value = null
      if (debounceTimer) clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => {
        loadRecommendations()
      }, 300)
    }

    const placeOrder = async () => {
      if (items.value.length === 0) return
      submitting.value = true
      error.value = null
      try {
        const payload = {
          budget: budget.value,
          items: items.value.map(item => ({
            sku: item.item_sku,
            quantity: item.quantity
          }))
        }
        const order = await api.createRestockOrder(payload)
        const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
        const deliveryDate = new Date(order.expected_delivery)
        const formattedDate = isNaN(deliveryDate.getTime())
          ? order.expected_delivery
          : deliveryDate.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' })

        successMessage.value = t('restocking.orderSuccess', {
          orderNumber: order.order_number,
          date: formattedDate
        })

        await loadRecommendations()
      } catch (err) {
        error.value = 'Failed to place restock order: ' + err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)

    return {
      t,
      loading,
      error,
      submitting,
      successMessage,
      budget,
      recommendations,
      items,
      currentCurrency,
      translateProductName,
      formatCurrency,
      onBudgetInput,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.budget-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-value {
  font-size: 1.75rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.budget-slider {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: #e2e8f0;
  outline: none;
  -webkit-appearance: none;
  appearance: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  border: 3px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  cursor: pointer;
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  border: 3px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  cursor: pointer;
}

.budget-range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #94a3b8;
}

.success-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  color: #065f46;
  padding: 1rem 1.25rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
  font-size: 0.938rem;
  font-weight: 500;
}

.success-link {
  color: #065f46;
  font-weight: 700;
  text-decoration: underline;
  white-space: nowrap;
  margin-left: 1rem;
}

.item-name {
  font-weight: 500;
  color: #0f172a;
}

.item-sku {
  font-size: 0.75rem;
  color: #64748b;
}

.partial-badge {
  margin-left: 0.5rem;
}

.partial-note {
  font-size: 0.75rem;
  color: #64748b;
  margin-top: 0.125rem;
}

.skipped-note {
  font-size: 0.813rem;
  color: #64748b;
  font-style: italic;
  padding: 0.75rem;
  text-align: center;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

.place-order-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 1.25rem;
  padding-top: 1.25rem;
  border-top: 1px solid #f1f5f9;
}

.place-order-btn {
  background: #2563eb;
  color: white;
  border: none;
  padding: 0.75rem 1.75rem;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
</style>
