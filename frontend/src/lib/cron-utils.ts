const daysOfWeek = [
  { value: 0, label: 'Sun', short: 'S' },
  { value: 1, label: 'Mon', short: 'M' },
  { value: 2, label: 'Tue', short: 'T' },
  { value: 3, label: 'Wed', short: 'W' },
  { value: 4, label: 'Thu', short: 'T' },
  { value: 5, label: 'Fri', short: 'F' },
  { value: 6, label: 'Sat', short: 'S' },
];

export function parseCron(cron: string) {
  const parts = cron.split(' ');
  if (parts.length !== 5) return { minute: 0, hour: 9, days: [1, 2, 3, 4, 5] };
  const m = parseInt(parts[0]);
  const h = parseInt(parts[1]);
  const dow = parts[4];
  let days: number[] = [];
  if (dow === '*') days = [0, 1, 2, 3, 4, 5, 6];
  else if (dow.includes('-')) {
    const [start, end] = dow.split('-').map(Number);
    for (let i = start; i <= end; i++) days.push(i);
  } else if (dow.includes(',')) days = dow.split(',').map(Number);
  else if (!isNaN(Number(dow))) days = [Number(dow)];
  return { minute: isNaN(m) ? 0 : m, hour: isNaN(h) ? 9 : h, days };
}

export function buildCron(minute: number, hour: number, days: number[]) {
  const daysStr = days.length === 7 || days.length === 0 ? '*' : days.sort().join(',');
  return `${minute} ${hour} * * ${daysStr}`;
}

export function humanizeSchedule(minute: number, hour: number, days: number[]) {
  const time = `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
  if (days.length === 7) return `Every day at ${time}`;
  if (days.length === 5 && days.every((d, i) => d === i + 1)) return `Weekdays at ${time}`;
  if (days.length === 2 && days.includes(0) && days.includes(6)) return `Weekends at ${time}`;
  if (days.length === 1) return `${daysOfWeek[days[0]].label} at ${time}`;
  return `${days.map((d) => daysOfWeek[d].label).join(', ')} at ${time}`;
}
