from datetime import date
from io import BytesIO
from pathlib import Path
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

from dashboard_data import prepare_data, filter_period, prediction_metrics, station_summary, export_csv

ROOT = Path(__file__).resolve().parent


class DataTests(unittest.TestCase):
    def test_repository_data_and_end_day(self):
        df, q = prepare_data((ROOT / 'analysis_result.csv').read_bytes())
        self.assertEqual(len(df), 168)
        self.assertEqual(q['excluded'], 0)
        view = filter_period(df, '설비ID', ['MOTOR-001'], '측정시각', date(2026, 9, 21), date(2026, 9, 21))
        self.assertEqual(len(view), 24)
        self.assertEqual(view['측정시각'].max().hour, 23)
        self.assertLess(prediction_metrics(view)['count'], len(view))

    def test_invalid_values_and_encoding(self):
        sample = pd.read_csv(ROOT / 'analysis_result.csv').head(3)
        sample.loc[0, '측정시각'] = 'invalid'
        sample['온도_C'] = ['bad', 'inf', '40']
        for encoding in ['utf-8-sig', 'cp949']:
            df, q = prepare_data(sample.to_csv(index=False).encode(encoding))
            self.assertEqual(q['excluded'], 1)
            self.assertTrue(pd.isna(df.iloc[0]['온도_C']))
        with self.assertRaisesRegex(ValueError, '필수 열'):
            prepare_data(b'bad\n1')

    def test_metrics_and_empty_prediction(self):
        df = pd.DataFrame({'다음온도_C': [10., 20., None], 'AI예측온도_C': [12., 16., 100.]})
        stats = prediction_metrics(df)
        self.assertEqual(stats['count'], 2)
        self.assertEqual(stats['mae'], 3.)
        self.assertEqual(stats['bias'], -1.)
        self.assertAlmostEqual(stats['rmse'], 10 ** .5)
        self.assertEqual(prediction_metrics(df.iloc[2:])['count'], 0)

    def test_station_rate_uses_paired_rows_and_handles_zero(self):
        df = pd.DataFrame({'역명': ['A', 'A', 'B'], '승차건수': [50., None, 0.],
                           '하차건수': [50., 50., 0.], '승하차건수': [100., None, 0.], '민원건수': [1., 99., 2.]})
        result = station_summary(df).set_index('역명')
        self.assertEqual(result.loc['A', '1만건당민원'], 100.)
        self.assertTrue(pd.isna(result.loc['B', '1만건당민원']))

    def test_csv_text_is_not_exported_as_formula(self):
        result = pd.read_csv(BytesIO(export_csv(pd.DataFrame({'memo': ['=1+1', 'regular']}))))
        self.assertEqual(result.iloc[0, 0], "'=1+1")


class ScreenTests(unittest.TestCase):
    def test_equipment_filters_sensor_review_and_navigation(self):
        at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.metric[0].value, '168건')
        self.assertEqual(len(at.tabs), 5)
        sensor = next(x for x in at.selectbox if x.label == '살펴볼 센서')
        sensor.set_value('진동_mm_s').run()
        self.assertFalse(at.exception)
        next(x for x in at.text_area if x.label == '확인 사항 및 조치 제안').input('테스트 검토 메모')
        next(x for x in at.button if x.label == '보고서에 반영').click().run()
        self.assertTrue(any('테스트 검토 메모' in x.value for x in at.text))
        # Invalid dates preserve the previously applied result.
        at.sidebar.date_input[0].set_value(date(2026, 9, 21))
        at.sidebar.date_input[1].set_value(date(2026, 9, 15))
        next(x for x in at.button if x.label == '조회 적용').click().run()
        self.assertTrue(at.error)
        self.assertEqual(at.metric[0].value, '168건')
        at.sidebar.date_input[1].set_value(date(2026, 9, 21))
        next(x for x in at.button if x.label == '조회 적용').click().run()
        self.assertEqual(at.metric[0].value, '24건')
        self.assertFalse(any('테스트 검토 메모' in x.value for x in at.text))
        at.sidebar.radio[0].set_value('역 이용 현황').run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.tabs), 3)
        next(x for x in at.radio if x.label == '요일 구분').set_value('주말').run()
        self.assertFalse(at.exception)
        self.assertEqual(at.metric[3].value, '4개')
        at.sidebar.radio[0].set_value('설비 분석').run()
        self.assertFalse(at.exception)
        self.assertEqual(at.metric[0].value, '24건')


if __name__ == '__main__':
    unittest.main()
