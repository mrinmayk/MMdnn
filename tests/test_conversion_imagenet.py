import os
import sys
import six
import unittest
import numpy as np
from six.moves import reload_module
import tensorflow as tf
from mmdnn.conversion.examples.imagenet_test import TestKit

from mmdnn.conversion.cntk.cntk_emitter import CntkEmitter
from mmdnn.conversion.tensorflow.tensorflow_emitter import TensorflowEmitter
from mmdnn.conversion.keras.keras2_emitter import Keras2Emitter
from mmdnn.conversion.pytorch.pytorch_emitter import PytorchEmitter

def _compute_SNR(x,y):
    noise = x - y
    noise_var = np.sum(noise ** 2) / len(noise) + 1e-7
    signal_energy = np.sum(y ** 2) / len(y)
    max_signal_energy = np.amax(y ** 2)
    SNR = 10 * np.log10(signal_energy / noise_var)
    PSNR = 10 * np.log10(max_signal_energy / noise_var)
    return SNR, PSNR


def _compute_max_relative_error(x,y):
    from six.moves import xrange
    rerror = 0
    index = 0
    for i in xrange(len(x)):
        den = max(1.0, np.abs(x[i]), np.abs(y[i]))
        if np.abs(x[i]/den - y[i] / den) > rerror:
            rerror = np.abs(x[i] / den - y[i] / den)
            index = i
    return rerror, index


def ensure_dir(f):
    d = os.path.dirname(f)
    if not os.path.exists(d):
        os.makedirs(d)


class CorrectnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        """ Set up the unit test by loading common utilities.
        """
        self.err_thresh = 0.15
        self.snr_thresh = 12
        self.psnr_thresh = 30

    def _compare_outputs(self, original_predict, converted_predict):
        self.assertEquals(len(original_predict), len(converted_predict))
        error, ind = _compute_max_relative_error(converted_predict, original_predict)
        SNR, PSNR = _compute_SNR(converted_predict, original_predict)
        print("error:", error)
        print("SNR:", SNR)
        print("PSNR:", PSNR)
        # self.assertGreater(SNR, self.snr_thresh)
        # self.assertGreater(PSNR, self.psnr_thresh)
        self.assertLess(error, self.err_thresh)


class TestModels(CorrectnessTest):

    image_path = "mmdnn/conversion/examples/data/seagull.jpg"
    cachedir = "tests/cache/"
    tmpdir = "tests/tmp/"

    @staticmethod
    def TensorFlowParse(architecture_name, image_path):
        from mmdnn.conversion.examples.tensorflow.extractor import tensorflow_extractor
        from mmdnn.conversion.tensorflow.tensorflow_parser import TensorflowParser

        # get original model prediction result
        original_predict = tensorflow_extractor.inference(architecture_name, TestModels.cachedir, image_path)
        del tensorflow_extractor

        # original to IR
        IR_file = TestModels.tmpdir + 'tensorflow_' + architecture_name + "_converted"
        parser = TensorflowParser(
            TestModels.cachedir + "imagenet_" + architecture_name + ".ckpt.meta",
            TestModels.cachedir + "imagenet_" + architecture_name + ".ckpt",
            None,
            "MMdnn_Output")
        parser.run(IR_file)
        del parser
        del TensorflowParser

        return original_predict


    @staticmethod
    def KerasParse(architecture_name, image_path):
        from mmdnn.conversion.examples.keras.extractor import keras_extractor
        from mmdnn.conversion.keras.keras2_parser import Keras2Parser

        # get original model prediction result
        original_predict = keras_extractor.inference(architecture_name, TestModels.cachedir, image_path)

        # download model
        model_filename = keras_extractor.download(architecture_name, TestModels.cachedir)
        del keras_extractor

        # original to IR
        IR_file = TestModels.tmpdir + 'keras_' + architecture_name + "_converted"
        parser = Keras2Parser(model_filename)
        parser.run(IR_file)
        del parser
        del Keras2Parser
        return original_predict


    @staticmethod
    def MXNetParse(architecture_name, image_path):
        from mmdnn.conversion.examples.mxnet.extractor import mxnet_extractor
        from mmdnn.conversion.mxnet.mxnet_parser import MXNetParser

        # download model
        architecture_file, weight_file = mxnet_extractor.download(architecture_name, TestModels.cachedir)

        # get original model prediction result
        original_predict = mxnet_extractor.inference(architecture_name, TestModels.cachedir, image_path)
        del mxnet_extractor

        # original to IR
        import re
        if re.search('.', weight_file):
            weight_file = weight_file[:-7]
        prefix, epoch = weight_file.rsplit('-', 1)
        model = (architecture_file, prefix, epoch, [3, 224, 224])

        IR_file = TestModels.tmpdir + 'mxnet_' + architecture_name + "_converted"
        parser = MXNetParser(model)
        parser.run(IR_file)
        del parser
        del MXNetParser

        return original_predict


    @staticmethod
    def CaffeParse(architecture_name, image_path):
        from mmdnn.conversion.examples.caffe.extractor import caffe_extractor

        # download model
        architecture_file, weight_file = caffe_extractor.download(architecture_name, TestModels.cachedir)

        # get original model prediction result
        original_predict = caffe_extractor.inference(architecture_name,architecture_file, weight_file, image_path)
        del caffe_extractor

        # original to IR
        from mmdnn.conversion.caffe.transformer import CaffeTransformer
        transformer = CaffeTransformer(architecture_file, weight_file, "tensorflow", None, phase = 'TRAIN')
        graph = transformer.transform_graph()
        data = transformer.transform_data()

        from mmdnn.conversion.caffe.writer import ModelSaver, PyWriter

        prototxt = graph.as_graph_def().SerializeToString()
        IR_file = TestModels.tmpdir + 'caffe_' + architecture_name + "_converted"
        pb_path = IR_file + '.pb'
        with open(pb_path, 'wb') as of:
            of.write(prototxt)
        print ("IR network structure is saved as [{}].".format(pb_path))

        import numpy as np
        npy_path = IR_file + '.npy'
        with open(npy_path, 'wb') as of:
            np.save(of, data)
        print ("IR weights are saved as [{}].".format(npy_path))

        return original_predict



    @staticmethod
    def CntkEmit(original_framework, architecture_name, architecture_path, weight_path, image_path):
        print("Testing {} from {} to CNTK.".format(architecture_name, original_framework))

        # IR to code
        converted_file = original_framework + '_cntk_' + architecture_name + "_converted"
        converted_file = converted_file.replace('.', '_')
        emitter = CntkEmitter((architecture_path, weight_path))
        emitter.run(converted_file + '.py', None, 'test')
        del emitter

        model_converted = __import__(converted_file).KitModel(weight_path)

        func = TestKit.preprocess_func[original_framework][architecture_name]
        img = func(image_path)
        predict = model_converted.eval({model_converted.arguments[0]:[img]})
        converted_predict = np.squeeze(predict)
        del model_converted
        del sys.modules[converted_file]
        os.remove(converted_file + '.py')
        return converted_predict


    @staticmethod
    def TensorflowEmit(original_framework, architecture_name, architecture_path, weight_path, image_path):
        print("Testing {} from {} to TensorFlow.".format(architecture_name, original_framework))

        # IR to code
        converted_file = original_framework + '_tensorflow_' + architecture_name + "_converted"
        converted_file = converted_file.replace('.', '_')
        emitter = TensorflowEmitter((architecture_path, weight_path))
        emitter.run(converted_file + '.py', None, 'test')
        del emitter

        # import converted model
        model_converted = __import__(converted_file).KitModel(weight_path)
        input_tf, model_tf = model_converted

        func = TestKit.preprocess_func[original_framework][architecture_name]
        img = func(image_path)
        input_data = np.expand_dims(img, 0)
        with tf.Session() as sess:
            init = tf.global_variables_initializer()
            sess.run(init)
            predict = sess.run(model_tf, feed_dict = {input_tf : input_data})
        del model_converted
        del sys.modules[converted_file]
        os.remove(converted_file + '.py')
        converted_predict = np.squeeze(predict)
        return converted_predict


    @staticmethod
    def PytorchEmit(original_framework, architecture_name, architecture_path, weight_path, image_path):
        import torch
        print("Testing {} from {} to PyTorch.".format(architecture_name, original_framework))

        # IR to code
        converted_file = original_framework + '_keras_' + architecture_name + "_converted"
        converted_file = converted_file.replace('.', '_')
        emitter = PytorchEmitter((architecture_path, weight_path))
        emitter.run(converted_file + '.py', converted_file + '.npy', 'test')
        del emitter

        # import converted model
        model_converted = __import__(converted_file).KitModel(converted_file + '.npy')
        model_converted.eval()

        func = TestKit.preprocess_func[original_framework][architecture_name]
        img = func(image_path)
        img = np.transpose(img, (2, 0, 1))
        img = np.expand_dims(img, 0).copy()
        input_data = torch.from_numpy(img)
        input_data = torch.autograd.Variable(input_data, requires_grad = False)

        predict = model_converted(input_data)
        predict = predict.data.numpy()

        del model_converted
        del sys.modules[converted_file]
        del torch
        os.remove(converted_file + '.py')
        os.remove(converted_file + '.npy')
        converted_predict = np.squeeze(predict)
        return converted_predict


    @staticmethod
    def KerasEmit(original_framework, architecture_name, architecture_path, weight_path, image_path):
        print("Testing {} from {} to Keras.".format(architecture_name, original_framework))

        # IR to code
        converted_file = original_framework + '_keras_' + architecture_name + "_converted"
        converted_file = converted_file.replace('.', '_')
        emitter = Keras2Emitter((architecture_path, weight_path))
        emitter.run(converted_file + '.py', None, 'test')
        del emitter

        # import converted model
        model_converted = __import__(converted_file).KitModel(weight_path)

        func = TestKit.preprocess_func[original_framework][architecture_name]
        img = func(image_path)
        input_data = np.expand_dims(img, 0)

        predict = model_converted.predict(input_data)
        converted_predict = np.squeeze(predict)

        del model_converted
        del sys.modules[converted_file]

        import keras.backend as K
        K.clear_session()

        os.remove(converted_file + '.py')
        return converted_predict


    test_table = {
        'keras' : {
            'vgg16'        : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
            'vgg19'        : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
            'inception_v3' : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
            'resnet50'     : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
            'densenet'     : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
            'xception'     : [TensorflowEmit, KerasEmit],
            'mobilenet'    : [TensorflowEmit, KerasEmit],
            'nasnet'       : [TensorflowEmit, KerasEmit],
        },
        'mxnet' : {
            'vgg19'                     : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
            'imagenet1k-inception-bn'   : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
            'imagenet1k-resnet-152'     : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
            'squeezenet_v1.1'           : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
            'imagenet1k-resnext-101-64x4d' : [CntkEmit, TensorflowEmit, PytorchEmit], # Keras is too slow
            'imagenet1k-resnext-50'        : [CntkEmit, TensorflowEmit, KerasEmit, PytorchEmit],
        },
        'caffe' : {
            # 'vgg19'         : [KerasEmit],
            'alexnet'       : [TensorflowEmit, KerasEmit],
            # 'inception_v1'  : [CntkEmit],
            # 'resnet152'     : [CntkEmit],
            # 'squeezenet'    : [CntkEmit]
         },
         'tensorflow' : {
            'inception_v1' : [TensorflowEmit, KerasEmit, PytorchEmit], # TODO: CntkEmit
         },
    }


    def _test_function(self, original_framework, parser):
        ensure_dir(self.cachedir)
        ensure_dir(self.tmpdir)

        for network_name in self.test_table[original_framework].keys():
            print("Testing {} model {} start.".format(original_framework, network_name))

            # get original model prediction result
            original_predict = parser(network_name, self.image_path)

            IR_file = TestModels.tmpdir + original_framework + '_' + network_name + "_converted"
            for emit in self.test_table[original_framework][network_name]:
                converted_predict = emit.__func__(
                    original_framework,
                    network_name,
                    IR_file + ".pb",
                    IR_file + ".npy",
                    self.image_path)

                self._compare_outputs(original_predict, converted_predict)

            try:
                os.remove(IR_file + ".json")
            except OSError:
                pass

            os.remove(IR_file + ".pb")
            os.remove(IR_file + ".npy")
            print("Testing {} model {} passed.".format(original_framework, network_name))

        print("Testing {} model all passed.".format(original_framework))


    def test_tensorflow(self):
        self._test_function('tensorflow', self.TensorFlowParse)


    def test_caffe(self):
        self._test_function('caffe', self.CaffeParse)


    def test_keras(self):
        self._test_function('keras', self.KerasParse)


    def test_mxnet(self):
        self._test_function('mxnet', self.MXNetParse)
