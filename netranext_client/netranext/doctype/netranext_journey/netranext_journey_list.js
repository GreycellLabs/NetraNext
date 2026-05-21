frappe.listview_settings["NetraNext Journey"] = {
	get_indicator: function (doc) {
		if (doc.status === "Completed") {
			return [__("Completed"), "green", "status,=,Completed"];
		} else if (doc.status === "In Progress") {
			return [__("In Progress"), "orange", "status,=,In Progress"];
		} else if (doc.status === "Cancelled") {
			return [__("Cancelled"), "red", "status,=,Cancelled"];
		}
	},

	formatters: {
		distance_km: function (value) {
			if (value) {
				return value.toFixed(2) + " km";
			}
			return "0 km";
		},
		duration_seconds: function (value) {
			if (!value) return "0 min";
			var minutes = Math.floor(value / 60);
			if (minutes >= 60) {
				var hours = Math.floor(minutes / 60);
				var mins = minutes % 60;
				return hours + "h " + mins + "m";
			}
			return minutes + " min";
		},
	},
};
