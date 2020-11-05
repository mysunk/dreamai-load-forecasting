import pandas as pd  # 데이터 전처리
import numpy as np  # 데이터 전처리
import os
from util_saint import *
from tqdm import tqdm

#%%
test = pd.read_csv('data/test.csv')
submission = pd.read_csv('submit/submission.csv')
# os.chdir('..')  # Changing Dir. (<main folder>)

test['Time'] = pd.to_datetime(test.Time)
test = test.set_index('Time')

print('Section [1]: Loading data...............')

comp_smape = []
key_idx = 0
agg = {}
for key in tqdm(test.columns):
    key_idx = key_idx + 1
    print([key, key_idx])
    prev_type = 2  # 전날 요일 타입
    curr_type = 2  # 예측날 요일 타입
    trainAR, testAR = AR_data_set(test, key, prev_type, curr_type)

    print('Section [2]: Data generation for training set...............')

    # [시간 예측을 위한 마지막 24pnt 추출]
    # NaN 값처리를 위해서 마지막 40pnts 추출 한 후에
    # interpolation하고 나서 24pnts 재추출
    """
    temp_test = test[key].iloc[8759 - 40:]
    temp_test = temp_test.interpolate(method='spline', order=2)
    temp_test = np.array(temp_test.values)
    """
    temp_test = test[key]
    temp_test[pd.isnull(temp_test)] = 0
    index_i, index_f = np.where(temp_test.values >0.0)[0][0], np.where(temp_test.values > 0.0)[0][-1]
    temp_test = temp_test.iloc[index_i:index_f + 1].values

    for i, data in enumerate(temp_test):
        if data == 0.0:
            if i < 2:
                temp_test[i] = temp_test[i - 1]
            else:
                temp_test[i] = 0.2 * temp_test[i - 2] + 0.8 * temp_test[i - 1]

    temp_test = temp_test[len(temp_test) - 24:len(temp_test) + 1]
    subm_24hrs = temp_test

    del temp_test

    fchk = 1  # filter length
    temp_idx = []
    smape_lin = []

    # 한 행씩 linear prediction을 테스트해보고 NaN이 발견된다면, 그 행을 제거.
    for chk_bad in range(0, len(trainAR[:, 0])):
        prev_smape = 200  # SMAPE 기준값
        nan_chk = 0  # NaN chk idx

        trainAR_temp = np.zeros([1, 24])  # pre-allocation
        testAR_temp = np.zeros([1, 24])  # pre-allocation

        # 한 행씩 테스트를 하기 위한 변수 설정
        for ii in range(0, 24):
            trainAR_temp[0, ii] = trainAR[chk_bad, ii]
            testAR_temp[0, ii] = testAR[chk_bad, ii]

        # linear prediction test
        lin_sampe, fcst_temp, pred_hyb = linear_prediction(trainAR_temp, testAR_temp, fchk, subm_24hrs)

        if np.isnan(lin_sampe):  # SMAPE가 NaN 경우, 그 행을 제거
            nan_chk = 1
        if np.isnan(np.sum(trainAR_temp)):  # chk_bad의 행이 NaN을 포함할 경우 제거
            nan_chk = 1
        if np.isnan(np.sum(testAR_temp)):  # chk_bad의 행이 NaN을 포함할 경우 제거
            nan_chk = 1

        if nan_chk == 1:  # NaN 값이 있는 행 넘버를 append
            temp_idx.append(chk_bad)

    # NaN 값이 나타난 data set은 제거
    trainAR = np.delete(trainAR, temp_idx, axis=0)
    testAR = np.delete(testAR, temp_idx, axis=0)

    del_smape = np.zeros([1, len(trainAR[:, 1])])
    prev_smape = 200
    fchk = 0

    # filter length 최적화
    for chk in range(3, 24):
        # filter length을 바꿔가며 Smape가 최소가 되는 값을 찾아감.
        lin_sampe, fcst_temp, pred_hyb = linear_prediction(trainAR, testAR, chk, subm_24hrs)
        if prev_smape > lin_sampe:
            fchk = chk
            prev_smape = lin_sampe

            # 필요없는 데이터 제거
    # 한 줄(하루)씩 제거해가면서 SMAPE 결과를 분석.
    for chk_lin in range(0, len(trainAR[:, 1])):
        trainAR_temp = np.delete(trainAR, chk_lin, axis=0)
        testAR_temp = np.delete(testAR, chk_lin, axis=0)
        lin_sampe, fcst_temp, pred_hyb = linear_prediction(trainAR_temp, testAR_temp, fchk, subm_24hrs)

        del_smape[0, chk_lin] = lin_sampe

    # SMAPE에 악영향을 주는 행을 제거
    trainAR = np.delete(trainAR, np.argmin(del_smape), axis=0)
    testAR = np.delete(testAR, np.argmin(del_smape), axis=0)
    del_smape = np.delete(del_smape, np.argmin(del_smape), axis=1)

    print('Section [3]: mitigating bad data...............')

    del nan_chk, lin_sampe, fcst_temp, pred_hyb, prev_smape, temp_idx

    # Lightgbm model
    lgb_fcst, lgb_smape = light_gbm_learn_gen(trainAR, testAR, subm_24hrs)

    # DNN model
    EPOCHS = 80
    Non_NNmodel, non_smape = non_linear_model_gen(trainAR, testAR, EPOCHS)

    # random forest model
    mac_fcst, Mac_smape = machine_learn_gen(trainAR, testAR, subm_24hrs)

    # linear model
    lin_sampe, fcst_temp, pred_hyb = linear_prediction(trainAR, testAR, fchk, subm_24hrs)

    # Similar day approach model
    temp_24hrs = np.zeros([1, 24])  # np.array type으로 변경.
    for qq in range(0, 24):
        temp_24hrs[0, qq] = subm_24hrs[qq]

    # Similar day approach model 최적화 (몇 개의 날(N)을 가져오는 게 좋은 지 평가.)
    prev_smape = 200
    fsim = 0  # N개의 날
    for sim_len in range(2, 5):
        sim_smape, fcst_sim = similar_approach(trainAR, testAR, sim_len, temp_24hrs)
        if prev_smape > sim_smape:
            fsim = sim_len
            prev_smape = sim_smape

    # Similar day approach model
    sim_smape, fcst_sim = similar_approach(trainAR, testAR, fsim, temp_24hrs)
    # ---------------------------------------------------------------------------------------

    minor_idx = 0  # Autoregression model에서 minor value가 나타나면,
    # 모델을 Autoregression model에서 similar day appreach로 변경 진행.

    # SMAPE가 linear model이 가장 작으면, 해당 결과 사용
    if (lin_sampe < non_smape) & (lin_sampe < Mac_smape) & (lin_sampe < sim_smape):
        fcst = np.zeros([1, 24])
        for qq in range(0, 24):
            fcst[0, qq] = fcst_temp[qq]

            if fcst_temp[qq] < 0:
                minor_idx = minor_idx + 1

    # SMAPE가 DNN model이 가장 작으면, 해당 결과 사용
    if (non_smape < lin_sampe) & (non_smape < Mac_smape) & (non_smape < sim_smape) & (non_smape < lgb_smape):
        temp_24hrs = np.zeros([1, 24])
        for qq in range(0, 24):
            temp_24hrs[0, qq] = subm_24hrs[qq]

        fcst = Non_NNmodel.predict(temp_24hrs)

    # SMAPE가 random forest model이 가장 작으면, 해당 결과 사용
    if (Mac_smape < non_smape) & (Mac_smape < lin_sampe) & (Mac_smape < sim_smape) & (Mac_smape < lgb_smape):
        fcst = mac_fcst

    # SMAPE가 lgbm model이 가장 작으면, 해당 결과 사용
    if (lgb_smape < non_smape) & (lgb_smape < lin_sampe) & (lgb_smape < sim_smape) & (lgb_smape < Mac_smape):
        fcst = mac_fcst

    # SMAPE가 Similar day approach model이 가장 작으면, 해당 결과 사용
    if (sim_smape < non_smape) & (sim_smape < lin_sampe) & (sim_smape < Mac_smape) & (sim_smape < lgb_smape):
        fcst = fcst_sim

    if (minor_idx > 0):
        fcst = fcst_sim

    # 각 SMAPE 결과 값을 정
    comp_smape.append([non_smape, lin_sampe, Mac_smape, sim_smape ,lgb_smape])

    a = pd.DataFrame()  # a라는 데이터프레임에 예측값을 정리합니다.

    print('Section [4]: Hour prediction model...............')
    for i in range(24):
        a['X2018_7_1_' + str(i + 1) + 'h'] = [fcst[0][i]]  # column명을 submission 형태에 맞게 지정합니다.

    if key_idx == 2:
        break

#%%
comp_smape = np.array(comp_smape)
models = ['non','lin','Mac','sim','lgb']
result = pd.DataFrame(index = test.columns, data = comp_smape,columns=models)
null_tr = (~pd.isnull(test)).sum(axis=0)
tmp = np.argmin(result.values, axis=1)
result['min_smape'] = np.nanmin(result.values, axis=1)
result['selected_model'] = [models[t] for t in tmp]
result['Null_points'] = null_tr.values
result = result.sort_values(by=['Null_points'])
result.to_csv('saint_result_2.csv',index=True)