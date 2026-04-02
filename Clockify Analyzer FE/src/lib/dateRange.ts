import dayjs from 'dayjs'
import type { Dayjs } from 'dayjs'
import isoWeek from 'dayjs/plugin/isoWeek'

dayjs.extend(isoWeek)

export const DATE_FMT = 'YYYY-MM-DD'

export type RangePreset = 'yesterday' | 'lastWeek' | 'custom'

export function yesterdayRange(): [Dayjs, Dayjs] {
  const d = dayjs().subtract(1, 'day')
  return [d, d]
}

export function lastWeekRange(): [Dayjs, Dayjs] {
  const end = dayjs().startOf('isoWeek').subtract(1, 'day')
  return [end.subtract(6, 'day'), end]
}

export function rangeForPreset(preset: RangePreset): [Dayjs, Dayjs] {
  return preset === 'yesterday' ? yesterdayRange() : lastWeekRange()
}
