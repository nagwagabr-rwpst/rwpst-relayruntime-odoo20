/** @odoo-module **/

import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { onWillUnmount } from "@odoo/owl";

const RELOAD_INTERVAL_MS = 5000;

export class WhatsAppCampaignMonitorKanbanController extends kanbanView.Controller {
    setup() {
        super.setup();
        if (this.props.context.whatsapp_monitor_auto_reload) {
            this._reloadInterval = setInterval(async () => {
                try {
                    await this.model.root.load();
                } catch {
                    // ignore transient load errors during reload
                }
            }, RELOAD_INTERVAL_MS);
            onWillUnmount(() => {
                clearInterval(this._reloadInterval);
            });
        }
    }
}

export const whatsAppCampaignMonitorKanbanView = {
    ...kanbanView,
    Controller: WhatsAppCampaignMonitorKanbanController,
};

registry.category("views").add("whatsapp_campaign_monitor_kanban", whatsAppCampaignMonitorKanbanView);
