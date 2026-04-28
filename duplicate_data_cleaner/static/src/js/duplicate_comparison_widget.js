/** @odoo-module **/
/**
 * duplicate_comparison_widget.js
 * ================================
 * OWL component that renders duplicate records side-by-side
 * and lets the user select the master record before merging.
 *
 * Registered as a field widget "duplicate_comparison" used inside
 * the duplicate.group comparison form on the record_ids One2many.
 */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const COMPARISON_FIELDS = ["record_name", "record_email", "record_phone", "record_ref"];
const FIELD_LABELS = {
    record_name: "Name",
    record_email: "Email",
    record_phone: "Phone",
    record_ref: "Reference",
};

/**
 * DuplicateComparisonWidget
 * --------------------------
 * Shows a table where each column is one duplicate record.
 * Cells that differ across records are highlighted in amber.
 * Selecting a radio button marks a record as master.
 */
class DuplicateComparisonWidget extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            records: [],
            masterRecordId: null,
            loading: true,
        });

        onWillStart(async () => {
            await this._loadRecords();
        });
    }

    async _loadRecords() {
        const groupId = this.props.record.resId;
        if (!groupId) {
            this.state.loading = false;
            return;
        }

        // Read the duplicate.record entries for this group
        const rawRecords = await this.orm.searchRead(
            "duplicate.record",
            [["group_id", "=", groupId]],
            ["id", "record_id", "record_name", "record_email", "record_phone", "record_ref", "is_master", "is_archived"],
            { order: "id asc" }
        );

        this.state.records = rawRecords;

        // Pre-select the current master
        const masterEntry = rawRecords.find((r) => r.is_master);
        if (masterEntry) {
            this.state.masterRecordId = masterEntry.record_id;
        } else if (rawRecords.length > 0) {
            this.state.masterRecordId = rawRecords[0].record_id;
        }

        this.state.loading = false;
    }

    /**
     * Determine if a field value differs across at least one other record.
     * Used to highlight differing cells.
     */
    _isDifferent(fieldName, value) {
        const values = this.state.records.map((r) => r[fieldName] || "");
        const unique = new Set(values);
        return unique.size > 1;
    }

    /**
     * Called when user clicks a radio button to select the master.
     */
    async onSelectMaster(recordId) {
        this.state.masterRecordId = recordId;
        // Persist the master_record_id on the duplicate.group record
        await this.orm.write("duplicate.group", [this.props.record.resId], {
            master_record_id: recordId,
        });
        this.notification.add(this.env._t("Master record updated."), {
            type: "info",
            sticky: false,
        });
    }
}

DuplicateComparisonWidget.template = "duplicate_data_cleaner.DuplicateComparisonWidget";
DuplicateComparisonWidget.props = {
    ...standardFieldProps,
};

registry.category("fields").add("duplicate_comparison", DuplicateComparisonWidget);

export { DuplicateComparisonWidget };


/**
 * DuplicateDashboard
 * -------------------
 * Client action registered as "duplicate_cleaner_dashboard".
 * Fetches live stats from the scanner and renders a simple KPI dashboard.
 */
class DuplicateDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            data: null,
        });

        onWillStart(async () => {
            await this._loadData();
        });
    }

    async _loadData() {
        try {
            const data = await this.orm.call("duplicate.scanner", "get_dashboard_data", []);
            this.state.data = data;
        } catch (e) {
            console.error("Dashboard load error", e);
        } finally {
            this.state.loading = false;
        }
    }

    async onScanClick() {
        this.state.loading = true;
        try {
            await this.orm.call("duplicate.scanner", "scan_all", []);
            await this._loadData();
        } finally {
            this.state.loading = false;
        }
    }

    onViewGroupsClick() {
        this.action.doAction("duplicate_data_cleaner.action_duplicate_groups");
    }
}

DuplicateDashboard.template = "duplicate_data_cleaner.DuplicateDashboard";
DuplicateDashboard.props = ["*"];

registry.category("actions").add("duplicate_cleaner_dashboard", DuplicateDashboard);

export { DuplicateDashboard };
