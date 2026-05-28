frappe.ui.form.on('Employee Checkin', {
    refresh: function(frm) {
        // Hide standard photo preview to prevent duplicate image rendering
        if (frm.fields_dict.photo_preview) {
            frm.set_df_property('photo_preview', 'hidden', 1);
        }

        // Handle custom photo display
        if (frm.doc.photo_proof) {
            let $photo_wrapper = frm.get_field('photo_proof').$wrapper;
            
            // Hide Frappe's native link and image displays via CSS to avoid timing issues
            if (!$('#custom-photo-proof-css').length) {
                $('<style id="custom-photo-proof-css">').text(`
                    [data-fieldname="photo_proof"] .control-input,
                    [data-fieldname="photo_proof"] .control-value,
                    [data-fieldname="photo_proof"] .attached-file-link,
                    [data-fieldname="photo_proof"] .attach-image-display {
                        display: none !important;
                    }
                `).appendTo('head');
            }
            
            // Remove any previously injected custom html
            $photo_wrapper.find('.custom-photo-container').remove();
            
            let img_url = frm.doc.photo_proof;
            let custom_html = `
                <div class="custom-photo-container" style="position: relative; display: inline-block; margin-top: 10px; max-width: 100%; overflow: hidden; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <img src="${img_url}" style="display: block; max-width: 100%; max-height: 400px; transition: transform 0.3s ease;" />
                    <div class="photo-overlay" style="position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.3); opacity: 0; transition: opacity 0.3s ease; display: flex; align-items: flex-start; justify-content: flex-end; padding: 10px;">
                        <a href="${img_url}" target="_blank" title="View Full Image" style="color: white; background: rgba(0,0,0,0.6); width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 5px rgba(0,0,0,0.2); transition: background 0.2s;">
                            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="15 3 21 3 21 9"></polyline>
                                <polyline points="9 21 3 21 3 15"></polyline>
                                <line x1="21" y1="3" x2="14" y2="10"></line>
                                <line x1="3" y1="21" x2="10" y2="14"></line>
                            </svg>
                        </a>
                    </div>
                </div>
            `;
            
            let $container = $photo_wrapper.find('.control-input-wrapper');
            if ($container.length === 0) {
                $container = $photo_wrapper; // Fallback
            }
            $container.append(custom_html);
            
            // Add hover effects via JS
            $photo_wrapper.find('.custom-photo-container').hover(
                function() { 
                    $(this).find('.photo-overlay').css('opacity', '1'); 
                    $(this).find('img').css('transform', 'scale(1.02)');
                },
                function() { 
                    $(this).find('.photo-overlay').css('opacity', '0'); 
                    $(this).find('img').css('transform', 'scale(1)');
                }
            );
            
            $photo_wrapper.find('.photo-overlay a').hover(
                function() { $(this).css('background', 'rgba(0,0,0,0.8)'); },
                function() { $(this).css('background', 'rgba(0,0,0,0.6)'); }
            );
        }

        if (frm.doc.latitude && frm.doc.longitude) {
            // Use an OpenStreetMap embed for a free map with a pin marker
            let lat = frm.doc.latitude;
            let lng = frm.doc.longitude;
            let bbox = `${lng-0.005},${lat-0.005},${lng+0.005},${lat+0.005}`;
            let map_html = `
                <div style="border: 1px solid #d1d8dd; border-radius: 4px; overflow: hidden; margin-top: 10px; height: 250px; position: relative;">
                    <iframe width="100%" height="295" frameborder="0" scrolling="no" marginheight="0" marginwidth="0" 
                    src="https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&amp;layer=mapnik&amp;marker=${lat}%2C${lng}"
                    style="position: absolute; top: 0; left: 0; border: none;">
                    </iframe>
                </div>
                <div style="text-align:right; font-size: 11px; margin-top: 4px;">
                    <a href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=16/${lat}/${lng}" target="_blank">View Larger Map</a>
                </div>
            `;
            frm.get_field('location_map').$wrapper.html(map_html);
        } else {
            frm.get_field('location_map').$wrapper.html('<div class="text-muted" style="padding: 15px; background: #f8f9fa; border-radius: 4px; margin-top: 10px;">No location coordinates available for this check-in.</div>');
        }
    }
});
