// Get all the checkboxes with solved class
const checkboxes = document.querySelectorAll('.solved');

// Add event listener to each checkbox: persist the status and update the
// row highlight through the same function used on initial page load, so
// the highlight logic only lives in one place.
checkboxes.forEach((checkbox) => {
  checkbox.addEventListener('change', (event) => {
    // Get the row element and the attributes
    const row = event.target.parentElement.parentElement;
    const rowId = row.id;
    const tableId = row.closest('table').id;
    const checked = event.target.checked;

    // Save the table row status to local storage
    saveTableRowStatus(tableId, rowId, checked);

    // Update the row highlight
    setSolvedRowsBackground(checkbox);
  });
});

// Load the table row status from local storage and tick the checkboxes
checkboxes.forEach((checkbox) => {
  // Get the row element
  const row = checkbox.parentElement.parentElement;
  const rowId = row.id;
  // Get the id of the parent table
  const tableId = row.closest('table').id;
  const storedStatus = loadTableRowStatus(tableId, rowId);
  // Set the checkbox checked status
  checkbox.checked = storedStatus;

  // Change row background color
  setSolvedRowsBackground(checkbox);
});

/**
 * Set background color of the solved row
 * @param {Element} checkbox 
 */
function setSolvedRowsBackground(checkbox) {
  console.log('Set solved')
  const row = checkbox.closest("tr");
      if (checkbox.checked) {
        row.classList.remove("row-unsolved");
        row.classList.add("row-solved");
      } else {
        row.classList.remove("row-solved");
        row.classList.add("row-unsolved");
      }
}

/**
 * Store row status in local storage
 * @param {Attr} tableId - id of the parent table
 * @param {Attr} rowId - id of the row
 * @param {Attr} checked - checkbox checked status
 */
function saveTableRowStatus(tableId, rowId, checked) {
  // Create a unique key using tableId and rowId
  const key = `${tableId}-${rowId}`;
  if (checked) {
    // Store the status in local storage
    localStorage.setItem(key, true);
  } else {
    // Remove the status from local storage
    localStorage.removeItem(key);
  }
}

/**
 * Load row status from the local storage
 * @param {Attr} tableId - id of the parent table
 * @param {Attr} rowId - id of the row
 * @returns Return the stored status as boolean
 */
function loadTableRowStatus(tableId, rowId) {
  // Create the unique key
  const key = `${tableId}-${rowId}`;
  return localStorage.getItem(key) === 'true';
}

/**
 * Add table sort on the table header click
 * @param {Number} columnIndex - columns index (0,1,2,...)
 * @param {Element} tableId - id of the parent table
 */
function sortTable(columnIndex, tableId) {
  var table, rows, switching, i, x, y, shouldSwitch;
  table = document.getElementById(tableId);
  switching = true;
  while (switching) {
    switching = false;
    rows = table.rows;
    for (i = 1; i < rows.length - 1; i++) {
      shouldSwitch = false;
      x = rows[i].getElementsByTagName("TD")[columnIndex];
      y = rows[i + 1].getElementsByTagName("TD")[columnIndex];
      if (x.innerHTML.toLowerCase() > y.innerHTML.toLowerCase()) {
        shouldSwitch = true;
        break;
      }
    }
    if (shouldSwitch) {
      rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
      switching = true;
    }
  }
}